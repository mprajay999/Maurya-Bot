import streamlit as st
import json
import pandas as pd
from datetime import datetime
import os
import re

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
        
        # Convert numeric columns
        numeric_cols = ['Unrestr.Stock', 'Current Tons', 'Safety Stock', 'Open Cust Ord', 
                        'In Transit', 'Open Prod Ord', 'Open Purch Ord']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        # Calculate summary
        summary = {
            'total_items': len(df),
            'total_plants': df['Plant'].nunique(),
            'total_current_tons': round(df['Current Tons'].sum(), 2),
            'materials_below_safety': len(df[df['Unrestr.Stock'] < df['Safety Stock']]),
            'total_open_orders': round(df['Open Cust Ord'].sum(), 2),
            'total_in_transit': round(df['In Transit'].sum(), 2),
        }
        
        return df, summary
    
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None, None

# Smart data retrieval function
def get_relevant_data(df, query, summary):
    """Intelligently retrieve only relevant data based on the query"""
    query_lower = query.lower()
    relevant_data = {'summary': summary}
    
    # Extract material codes
    material_codes = re.findall(r'\b\d{6,10}\b', query)
    
    if material_codes:
        materials = df[df['Material'].astype(str).isin(material_codes)]
        relevant_data['specific_materials'] = materials.head(10).to_dict('records')
        relevant_data['query_type'] = 'specific_material'
    
    elif any(word in query_lower for word in ['low stock', 'below safety', 'need reorder', 'critically low', 'reordering']):
        low_stock = df[df['Unrestr.Stock'] < df['Safety Stock']].nlargest(20, 'Safety Stock')
        relevant_data['low_stock_items'] = low_stock[
            ['Material', 'Description', 'Unrestr.Stock', 'Safety Stock', 'Plant Name', 'Current Tons']
        ].to_dict('records')
        relevant_data['query_type'] = 'low_stock'
    
    elif any(word in query_lower for word in ['top', 'highest', 'most', 'largest', 'biggest']):
        top_items = df.nlargest(15, 'Current Tons')
        relevant_data['top_items'] = top_items[
            ['Material', 'Description', 'Current Tons', 'Plant Name', 'Material Type']
        ].to_dict('records')
        relevant_data['query_type'] = 'top_items'
    
    elif 'plant' in query_lower:
        plant_numbers = re.findall(r'\b\d{4}\b', query)
        if plant_numbers:
            plant_num = float(plant_numbers[0])
            plant_data = df[df['Plant'].astype(float) == plant_num]
            if len(plant_data) > 0:
                relevant_data['plant_inventory'] = plant_data.head(30)[
                    ['Material', 'Description', 'Current Tons', 'Unrestr.Stock', 'Material Type']
                ].to_dict('records')
                relevant_data['plant_number'] = plant_num
                relevant_data['query_type'] = 'plant_specific'
    
    elif any(mat_type in query_lower for mat_type in ['emt', 'rigid', 'elbow', 'coupling', 'conduit']):
        for mat_type in ['emt', 'rigid', 'elbow', 'coupling', 'conduit']:
            if mat_type in query_lower:
                type_data = df[df['Material Type'].str.contains(mat_type, case=False, na=False)]
                if len(type_data) == 0:
                    type_data = df[df['Description'].str.contains(mat_type, case=False, na=False)]
                
                relevant_data['material_type_summary'] = {
                    'total_items': len(type_data),
                    'total_tons': round(type_data['Current Tons'].sum(), 2),
                    'by_plant': type_data.groupby('Plant Name')['Current Tons'].sum().round(2).to_dict()
                }
                relevant_data['sample_items'] = type_data.head(15)[
                    ['Material', 'Description', 'Current Tons', 'Plant Name']
                ].to_dict('records')
                relevant_data['material_type'] = mat_type
                relevant_data['query_type'] = 'material_type'
                break
    
    elif any(word in query_lower for word in ['transit', 'in transit', 'shipping']):
        in_transit = df[df['In Transit'] > 0].nlargest(20, 'In Transit')
        relevant_data['in_transit_items'] = in_transit[
            ['Material', 'Description', 'In Transit', 'Plant Name']
        ].to_dict('records')
        relevant_data['query_type'] = 'transit'
    
    elif any(word in query_lower for word in ['order', 'purchase', 'customer order']):
        open_orders = df[df['Open Purch Ord'] > 0].nlargest(20, 'Open Purch Ord')
        relevant_data['open_orders'] = open_orders[
            ['Material', 'Description', 'Open Purch Ord', 'Open Cust Ord', 'Plant Name']
        ].to_dict('records')
        relevant_data['query_type'] = 'orders'
    
    else:
        relevant_data['query_type'] = 'general'
        relevant_data['top_items'] = df.nlargest(10, 'Current Tons')[
            ['Material', 'Description', 'Current Tons', 'Plant Name']
        ].to_dict('records')
    
    return relevant_data

# Load the data
df, summary = load_inventory_data()

if df is None:
    st.error("Failed to load inventory data. Please check the file paths.")
    st.stop()

# Simple header
st.markdown('<h1 class="main-title">🤖 Inventory Assistant</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Ask me anything about your steel plant inventory</p>', unsafe_allow_html=True)

# Minimal sidebar (collapsed by default)
with st.sidebar:
    st.markdown("### Settings")
    
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    
    st.divider()
    
    st.markdown("### Quick Info")
    st.caption(f"📦 {summary['total_items']:,} items tracked")
    st.caption(f"🏭 {summary['total_plants']} plants")
    if summary['materials_below_safety'] > 0:
        st.caption(f"⚠️ {summary['materials_below_safety']} items below safety stock")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
user_input = None

if prompt := st.chat_input("Type your question here..."):
    user_input = prompt

# Process user input
if user_input:
    prompt = user_input
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Generate assistant response
    with st.chat_message("assistant"):
        try:
            import requests
            
            with st.spinner("⏳ Getting response from OpenAI..."):
                # Get relevant data (optimized approach)
                relevant_data = get_relevant_data(df, prompt, summary)
            
            # Create focused context
            context = f"""You are an expert inventory assistant for a steel manufacturing plant with {summary['total_items']:,} items across {summary['total_plants']} plants.

OVERALL SUMMARY:
- Total items: {summary['total_items']:,}
- Total plants: {summary['total_plants']}
- Total stock: {summary['total_current_tons']:,.1f} tons
- Items below safety: {summary['materials_below_safety']}
- Open orders: {summary['total_open_orders']:,.1f}
- In transit: {summary['total_in_transit']:,.1f}

RELEVANT DATA (Query Type: {relevant_data['query_type']}):
{json.dumps({k: v for k, v in relevant_data.items() if k not in ['summary']}, indent=2)}

INSTRUCTIONS:
1. Provide clear, actionable insights
2. Use specific numbers and material codes
3. Format responses professionally with proper structure
4. Highlight critical information (low stock, high values)
5. Be concise but comprehensive
6. Use bullet points for multiple items
7. Include plant names and locations when relevant"""

            # Prepare API messages
            api_messages = [{"role": "user", "content": context}]
            
            for msg in st.session_state.messages[-7:-1]:
                api_messages.append({"role": msg["role"], "content": msg["content"]})
            
            api_messages.append({"role": "user", "content": prompt})
            
            # Get API key
            api_key = os.getenv("OpenAI_API_Key") or os.getenv("OPENAI_API_KEY")
            
            print(f"[DEBUG] API key found: {api_key is not None}")
            
            if not api_key:
                st.markdown("❌ **OpenAI API key not found.** Please set the API key in your .env file.")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "Error: OpenAI API key not configured."
                })
            else:
                print(f"[DEBUG] Sending request to OpenAI API...")
                
                response = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    },
                    json={
                        "model": "gpt-4-turbo",
                        "max_tokens": 2000,
                        "messages": api_messages
                    },
                    timeout=30
                )
                
                print(f"[DEBUG] Response status: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    full_response = result['choices'][0]['message']['content']
                    st.markdown(full_response)
                    
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": full_response
                    })
                    print(f"[DEBUG] Response added successfully")
                else:
                    error_msg = f"❌ **API Error {response.status_code}**\n\n{response.text[:300]}"
                    print(f"[DEBUG] API error: {response.status_code}")
                    st.markdown(error_msg)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": error_msg
                    })
                    
        except requests.exceptions.Timeout as e:
            error_msg = "❌ **Request Timeout** - API took too long to respond. Please try again."
            print(f"[DEBUG] Timeout: {str(e)}")
            st.markdown(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })
            
        except requests.exceptions.ConnectionError as e:
            error_msg = "❌ **Connection Error** - Please check your internet connection."
            print(f"[DEBUG] Connection error: {str(e)}")
            st.markdown(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })
            
        except Exception as e:
            error_msg = f"❌ **Error**: {str(e)}"
            print(f"[DEBUG] Exception: {str(e)}")
            import traceback
            print(traceback.format_exc())
            st.markdown(error_msg)
            st.session_state.messages.append({
                "role": "assistant",
                "content": error_msg
            })