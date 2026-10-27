import ollama 
from ollama import chat

user_prompt = input("Enter a prompt: ")

response = ollama.systemone(
    model='tev1:0.8b',
    state=user_prompt,
    questions={
        'coding': {
            'type': 'noul',
            'instructions': 'Classify the user request whether it is related to coding . Coding includes writing, debugging, explaining, reviewing, or modifying code; programming languages; shell commands; scripts; APIs; software development; and technical implementation.',
            'criteria': {
                'true': 'The primary intent is related to writing, debugging, reviewing, explaining, or modifying code or implementing software.',
                'false': 'The primary intent is not related to writing, debugging, reviewing, explaining, or modifying code or implementing software.',
            },
        },
        'research': {
            'type': 'noul',
            'instructions': 'Classify the user request whether it is related to research. Research includes literature reviews, data collection, analysis, and interpretation.',
            'criteria': {
                'true': 'The primary intent is related to literature reviews, data collection, analysis, and interpretation.',
                'false': 'The primary intent is not related to literature reviews, data collection, analysis, and interpretation.',
            },
        },
        'general': {
            'type': 'noul',
            'instructions': 'Classify the user request whether it is a general or casual exchange. General includes conversation, plain explanations, opinions, brainstorming, and everyday questions or text.',
            'criteria': {
                'true': 'The primary intent is a conversational answer, explanation, opinion, or everyday question, with nothing to build and no sources to gather.',
                'false': 'The primary intent is implementing software or carrying out an evidence-based investigation.',
            },
        },
    },
)
print(response.answers)
#print(response.answers['coding'].noul)
#print(response.answers['research'].noul)
#print(response.answers['general'].noul)

scores = {
    'coding': response.answers['coding'].noul,
    'research': response.answers['research'].noul,
    'general': response.answers['general'].noul,
}
highest_score = max(scores, key=scores.get)
#print(f"The user request is related to {highest_score}.")
if highest_score == 'coding':
    print("The user request is related to coding. The score is ", scores['coding'])
    response = chat(
    model='nemotron-3.5-bolt:e4b',
    messages=[{'role': 'user', 'content': user_prompt}],)
    print(response.message.content)
elif highest_score == 'research':
    print("The user request is related to research. The score is ", scores['research'])
    response = chat(
    model='qwen3.8:latest',
    messages=[{'role': 'user', 'content': user_prompt + " Please provide a detailed research plan and a list of sources to be used."}],)
    print(response.message.content)
elif highest_score == 'general':
    print("The user request is general. The score is ", scores['general'])
    response = chat(
    model='gpt-oss-safeguard:latest',
    messages=[{'role': 'user', 'content': user_prompt}],)
    print(response.message.content)