import streamlit as st
import json
import pandas as pd
from datetime import datetime
import os
import re
import requests
import traceback
from io import StringIO

# Load .env file manually
def load_env_file():
    env_path = '/Users/mprajay999/Maurya Bot/.env'
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            os.environ[key] = value
        except Exception as e:
            st.error(f"Error loading .env file: {e}")

# Load environment variables
load_env_file()


# Function to load data (cached)
@st.cache_data(ttl=300)
def load_inventory_data(csv_path='/Users/mprajay999/Maurya Bot/Power BI Invenotry Table.csv'):
    """Load and process the inventory data"""
    try:
        df = pd.read_csv(csv_path, dtype=str)
        df.columns = df.columns.str.strip()

        # Drop empty trailing columns
        df = df.loc[:, df.columns.str.strip() != '']
        
        # Convert numeric columns
        numeric_cols = ['Unrestr.Stock', 'Current Tons', 'Safety Stock', 'Open Cust Ord', 
                        'In Transit', 'Open Prod Ord', 'Open Purch Ord', 'Net Available',
                        'Total Open Delv', 'Open STO', 'Max Stock Lvl', 'Restric Stock',
                        'Blocked Stock', 'In Qual.Insp (Restr.)', 'Outer Diameter',
                        'Wall Thickness', 'Weekly Forecast', 'Days of Supply Available']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        return df
    
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None


def get_schema_prompt(df):
    """Build a compact schema description to send to the LLM (tiny token cost)."""
    lines = []
    lines.append("The DataFrame is called `df` and has the following columns:\n")
    lines.append(f"Total rows: {len(df):,}\n")
    lines.append("| # | Column | Dtype | Sample Values |")
    lines.append("|---|--------|-------|---------------|")
    for i, col in enumerate(df.columns, 1):
        dtype = str(df[col].dtype)
        # Get up to 5 unique non-null sample values
        samples = df[col].dropna().unique()[:5]
        sample_str = ", ".join([str(s)[:40] for s in samples])
        lines.append(f"| {i} | `{col}` | {dtype} | {sample_str} |")
    
    # Add unique value hints for key categorical columns
    cat_cols = ['Plant', 'Plant Name', 'Material Type', 'State', 'City', 
                'Organisation', 'Sub Category', 'Material Category', 'UOM', 'Country']
    lines.append("\n**Unique values for key columns:**")
    for col in cat_cols:
        if col in df.columns:
            uniques = df[col].dropna().unique()
            if len(uniques) <= 30:
                lines.append(f"- `{col}`: {list(uniques)}")
            else:
                lines.append(f"- `{col}`: {len(uniques)} unique values (e.g. {list(uniques[:8])})")
    
    # Add material code format info
    mat_lengths = df['Material'].str.len().value_counts()
    lines.append(f"\n**Material code formats:** {dict(mat_lengths.head(5))}")
    lines.append(f"**Sample material codes:** {list(df['Material'].unique()[:10])}")
    
    # Add key numeric stats
    lines.append("\n**Key stats:**")
    for col in ['Current Tons', 'Unrestr.Stock', 'Safety Stock']:
        if col in df.columns:
            lines.append(f"- `{col}`: min={df[col].min():.2f}, max={df[col].max():.2f}, mean={df[col].mean():.2f}")
    
    return "\n".join(lines)


SYSTEM_PROMPT = """You are a Pandas code generator for a steel plant inventory dataset.

The user will ask natural language questions about inventory data.
You must respond with ONLY a valid Python code block that uses pandas to query the DataFrame `df`.

RULES:
1. The DataFrame variable is always called `df` — it is already loaded, do NOT load or read any CSV.
2. Store your final answer in a variable called `result`.
3. `result` MUST be a DataFrame with ALL relevant columns so the answer is detailed and complete.
4. Do NOT use print(). Do NOT import pandas (it's already imported).
5. Do NOT use `exec`, `eval`, `os`, `sys`, `subprocess`, or any file/network operations.
6. Use only pandas operations: filtering, groupby, agg, sort_values, nlargest, nsmallest, value_counts, etc.
7. Always handle string matching with `.str.contains(..., case=False, na=False)`.
8. Return your code inside a single ```python ... ``` block and nothing else.
9. If the question is unclear, make a reasonable assumption and write the query.
10. For "low stock" or "below safety stock", compare `Unrestr.Stock < Safety Stock`.
11. Keep results concise — use .head(20) for large outputs.

CRITICAL — ALWAYS RETURN RICH, DETAILED RESULTS:
- NEVER return just a single number or scalar. Always return a DataFrame with context.
- When asked "which plant has highest stock", return a DataFrame with Plant, Plant Name, City, State, total stock, item count — NOT just a number.
- When asked about materials, include: Material, Description, Plant Name, Current Tons, Unrestr.Stock, Safety Stock, and any other relevant columns.
- When grouping by plant, always include: Plant, Plant Name, City, State, Full Location.
- When grouping by material type, include: Material Type, total tons, item count, and top plants.
- For lookups by material code, return ALL columns for those materials.
- If user provides multiple material codes (space/comma separated or as a long number), try to split them into valid 5-digit or 10-digit codes and look up each.
- Always sort results meaningfully (e.g., descending by stock/tons).
- Include aggregated totals where useful (e.g., total tons, count of items).
"""


def call_openai(api_key, messages, max_tokens=1000):
    """Make a request to OpenAI API and return the response text."""
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        json={
            "model": "gpt-4-turbo",
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": messages
        },
        timeout=30
    )
    if response.status_code == 200:
        return response.json()['choices'][0]['message']['content'], None
    else:
        return None, f"API Error {response.status_code}: {response.text[:300]}"


def extract_code(text):
    """Extract Python code from a markdown code block."""
    # Try ```python ... ``` first
    match = re.search(r'```python\s*\n(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Try ``` ... ```
    match = re.search(r'```\s*\n(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def validate_code(code):
    """Basic safety check on generated code."""
    banned = ['import os', 'import sys', 'import subprocess', 'exec(', 'eval(', 
              'open(', '__import__', 'compile(', 'globals(', 'locals(',
              'shutil', 'pathlib', 'requests', 'urllib']
    for item in banned:
        if item in code:
            return False, f"Unsafe operation detected: `{item}`"
    return True, ""


def execute_pandas_query(df, code):
    """Safely execute the pandas code and return the result."""
    # Only expose df and pandas in the execution namespace
    local_ns = {'df': df.copy(), 'pd': pd}
    exec(code, {"__builtins__": {}}, local_ns)
    
    if 'result' not in local_ns:
        return None, "The generated code did not produce a `result` variable."
    
    return local_ns['result'], None


def format_result(result):
    """Convert the pandas result to a readable string for the LLM."""
    if isinstance(result, pd.DataFrame):
        if len(result) == 0:
            return "No matching records found."
        # Show up to 30 rows for detailed answers
        display_df = result.head(30)
        text = display_df.to_markdown(index=False)
        if len(result) > 30:
            text += f"\n\n... and {len(result) - 30} more rows (total: {len(result)} rows)"
        # Add summary stats for numeric columns
        num_cols = display_df.select_dtypes(include='number').columns
        if len(num_cols) > 0 and len(result) > 1:
            text += "\n\n**Totals:**\n"
            for col in num_cols:
                total = result[col].sum()
                if total > 0:
                    text += f"- {col}: {total:,.2f}\n"
        return text
    elif isinstance(result, pd.Series):
        return result.to_markdown()
    else:
        return str(result)


# ──────────────────────────────────────────
# Load the data
# ──────────────────────────────────────────
df = load_inventory_data()

if df is None:
    st.error("Failed to load inventory data. Please check the file paths.")
    st.stop()

schema_prompt = get_schema_prompt(df)

# ──────────────────────────────────────────
# UI
# ──────────────────────────────────────────
st.markdown('<h1 class="main-title">🤖 Inventory Assistant</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Ask me anything about your steel plant inventory</p>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("### Settings")
    
    show_code = st.toggle("🔍 Show generated query", value=False)
    
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    
    st.divider()
    
    st.markdown("### Quick Info")
    st.caption(f"📦 {len(df):,} items tracked")
    st.caption(f"🏭 {df['Plant'].nunique()} plants")
    below_safety = len(df[df['Unrestr.Stock'] < df['Safety Stock']])
    if below_safety > 0:
        st.caption(f"⚠️ {below_safety} items below safety stock")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        # Show code if it was stored
        if show_code and message["role"] == "assistant" and "pandas_code" in message:
            with st.expander("🔍 Pandas Query"):
                st.code(message["pandas_code"], language="python")

# Chat input
if prompt := st.chat_input("Type your question here..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Generate assistant response
    with st.chat_message("assistant"):
        api_key = os.getenv("OpenAI_API_Key") or os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            error_msg = "❌ **OpenAI API key not found.** Please set `OpenAI_API_Key` in your `.env` file."
            st.markdown(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
        else:
            try:
                with st.spinner("🧠 Generating query..."):
                    # ── STEP 1: Send schema + question → get Pandas code ──
                    step1_messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"SCHEMA:\n{schema_prompt}"},
                    ]
                    # Include recent conversation for context
                    for msg in st.session_state.messages[-6:-1]:
                        step1_messages.append({"role": msg["role"], "content": msg["content"]})
                    step1_messages.append({"role": "user", "content": prompt})

                    code_response, err = call_openai(api_key, step1_messages, max_tokens=800)
                
                if err:
                    st.markdown(f"❌ {err}")
                    st.session_state.messages.append({"role": "assistant", "content": f"Error: {err}"})
                else:
                    # Extract and validate code
                    pandas_code = extract_code(code_response)
                    is_safe, safety_msg = validate_code(pandas_code)
                    
                    if not is_safe:
                        st.markdown(f"⚠️ **Blocked unsafe query:** {safety_msg}")
                        st.session_state.messages.append({
                            "role": "assistant", "content": f"Blocked: {safety_msg}"
                        })
                    else:
                        # ── STEP 2: Execute the Pandas query locally ──
                        with st.spinner("📊 Running query on data..."):
                            result, exec_err = execute_pandas_query(df, pandas_code)
                        
                        if exec_err:
                            # If execution fails, retry once with the error message
                            retry_messages = step1_messages + [
                                {"role": "assistant", "content": f"```python\n{pandas_code}\n```"},
                                {"role": "user", "content": f"That code failed with error: {exec_err}\nPlease fix the code."}
                            ]
                            code_response2, err2 = call_openai(api_key, retry_messages, max_tokens=800)
                            if not err2:
                                pandas_code = extract_code(code_response2)
                                is_safe, _ = validate_code(pandas_code)
                                if is_safe:
                                    result, exec_err = execute_pandas_query(df, pandas_code)
                            
                            if exec_err:
                                st.markdown(f"❌ **Query execution failed:** {exec_err}")
                                st.session_state.messages.append({
                                    "role": "assistant", "content": f"Error: {exec_err}"
                                })
                            else:
                                exec_err = None  # cleared after retry
                        
                        if exec_err is None and result is not None:
                            result_str = format_result(result)
                            
                            # Show code if toggled
                            if show_code:
                                with st.expander("🔍 Pandas Query", expanded=True):
                                    st.code(pandas_code, language="python")
                            
                            # ── STEP 3: Send result → get natural language answer ──
                            with st.spinner("💬 Generating answer..."):
                                step3_messages = [
                                    {"role": "system", "content": (
                                        "You are a detailed inventory analyst for a steel manufacturing company. "
                                        "You are given the result of a data query. Your job is to give a THOROUGH, "
                                        "DETAILED, and INSIGHTFUL answer.\n\n"
                                        "RULES FOR YOUR RESPONSE:\n"
                                        "1. Always mention specific names — plant names, cities, states, material descriptions.\n"
                                        "2. Include exact numbers with proper formatting (commas, decimals).\n"
                                        "3. Use markdown tables when showing multiple items.\n"
                                        "4. Use bullet points for key insights.\n"
                                        "5. Add analysis — highlight if something is critically low, unusually high, etc.\n"
                                        "6. Compare values where relevant (e.g., stock vs safety stock).\n"
                                        "7. If showing a 'top' or 'highest', also mention the runner-ups for context.\n"
                                        "8. End with a brief actionable insight or recommendation when appropriate.\n"
                                        "9. NEVER say 'based on the data' or 'according to the query'. Just state facts directly.\n"
                                        "10. Do NOT mention pandas, code, queries, or DataFrames.\n"
                                        "11. Format large numbers with commas (e.g., 1,234.56 tons).\n"
                                        "12. If the result is empty or no matches found, say so clearly and suggest alternatives."
                                    )},
                                    {"role": "user", "content": f"User question: {prompt}\n\nQuery result:\n{result_str}"}
                                ]
                                
                                final_answer, err3 = call_openai(api_key, step3_messages, max_tokens=2000)
                            
                            if err3:
                                # Fallback: just show the raw result
                                st.markdown(f"📊 **Query Result:**\n\n{result_str}")
                                st.session_state.messages.append({
                                    "role": "assistant", "content": result_str, "pandas_code": pandas_code
                                })
                            else:
                                st.markdown(final_answer)
                                st.session_state.messages.append({
                                    "role": "assistant", "content": final_answer, "pandas_code": pandas_code
                                })

            except requests.exceptions.Timeout:
                error_msg = "❌ **Request Timeout** — API took too long. Please try again."
                st.markdown(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
            
            except requests.exceptions.ConnectionError:
                error_msg = "❌ **Connection Error** — Please check your internet connection."
                st.markdown(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
            
            except Exception as e:
                error_msg = f"❌ **Error**: {str(e)}"
                print(f"[DEBUG] Exception: {traceback.format_exc()}")
                st.markdown(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})