import ollama

# 1. Initialize the conversation history
messages = []

print("--- Chatting with gpt-oss:120b-cloud ---")
print("Type 'exit' or 'quit' to stop.\n")

while True:
    # 2. Get user input
    user_input = input("You: ")
    
    if user_input.lower() in ['exit', 'quit']:
        break

    # 3. Add user message to history
    messages.append({'role': 'user', 'content': user_input})

    try:
        # 4. Send the ENTIRE history to Ollama
        response = ollama.chat(model='gpt-oss:120b-cloud', messages=messages)

        # 5. Extract the AI's answer
        ai_response = response['message']['content']
        print(f"\nAI: {ai_response}\n")

        # 6. Add the AI's response to history so it remembers for next time
        messages.append({'role': 'assistant', 'content': ai_response})

    except Exception as e:
        print(f"Error: {e}")
        break