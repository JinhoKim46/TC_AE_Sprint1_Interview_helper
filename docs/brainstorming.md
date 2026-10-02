# objective
the interview helper app helps job seekers prepare for interviews by providing a platform to practice answering common interview questions, receive feedback, and improve their responses. The app aims to boost confidence and enhance interview performance through interactive features and personalized guidance. 

# how it works
1. in docs/applications/COMPANY/ROLE, user add job description, CV, and cover letter. 
2. user starts the app, and select which company and role they want to practice for.
3. Interview starts
4. After the interview, the app provides feedback, evalaute the user's performance, and suggest areas for improvement, and ending up decision based on the score.

# Planning th eproject
1. Interview related information, such as guideline, evaluation rubric, question bank are stored in docs. For more details, read docs/README.md. They are provided by ai-job-search tool by Mads Lorentzen. 
2. Overal understanding of the project is in docs/00-project-objective.md and it's based on the project description
3. Application related documents are stored in docs/applications/COMPANY/ROLE. For example, docs/applications/google/software-engineer. The documents are provided by ai-job-search tool by Mads Lorentzen.

# features
## Interview Helper App
1. user select the persona of the interviewer, i.e., personality (friendly, strict, etc.), professional background (HR, technical, etc.), and experience level (junior, senior, etc.).
2. user can choose the type of interview questions they want to practice, such as behavioral, technical, situational, or case study questions.
3. The agent model and provider should be agnostic to any. For example, this project, I will use OpenRouter with entry models, but for actual use, it should be able to use any provider and model, such as OpenAI, Anthropic, etc. The app should be designed to allow easy integration with different providers and models, enabling users to choose the one that best suits their needs and preferences. (implementation design)
4. the app stores the history of the user's practice sessions, including the questions asked, the user's responses, and the feedback provided. This allows users to track their progress over time and identify areas for improvement. for this, supabase can be used to store the data, and the app can provide visualizations and analytics to help users understand their performance trends and patterns. 
5. the app provides LLM-as-a-judge and JEV-as-a-judge to evaluate the user's responses and provide feedback. The LLM-as-a-judge can analyze the user's answers based on various criteria, such as clarity, relevance, and completeness, while the JEV-as-a-judge can assess the user's performance based on specific job requirements and industry standards. This dual evaluation system ensures that users receive comprehensive feedback that addresses both general interview skills and role-specific competencies.
6. the app can provide personalized recommendations for improvement based on the user's performance and feedback received. These recommendations can include tips for answering specific types of questions, suggestions for improving communication skills, and resources for further learning and development. By offering targeted guidance, the app helps users focus on areas that will have the greatest impact on their interview performance.
7. The interview agent uses text-to-speech (TTS) technology to read the questions aloud, creating a more realistic interview experience. This feature allows users to practice responding to questions in a conversational manner, simulating the dynamics of a real interview setting. Additionally, the app can provide options for users to adjust the voice and speech rate of the TTS system, catering to individual preferences and enhancing the overall user experience.
8. The user also choose writing mode or speech mode for answering the questions. In writing mode, users can type their responses, while in speech mode, they can speak their answers aloud. This flexibility allows users to practice in a way that best suits their comfort level and preferred communication style. The app can also provide real-time transcription of spoken responses, enabling users to review and refine their answers more effectively.
9. THe user should be able to set parameters of the app, such as the number of questions to be asked, the time limit for each response, and the difficulty level of the questions. This customization allows users to tailor their practice sessions to their specific needs and goals, ensuring a more effective and efficient preparation process. Additionally, the app can offer preset configurations for different interview scenarios, such as entry-level positions or senior management roles, providing users with a starting point for their practice sessions. also AI related parameters, such as temperature for reproducibility, and max tokens for response length, can be set by the user to control the behavior of the AI during the interview simulation.
10. Available menus are dashboard, interview,, history, settings, and help. The dashboard provides an overview of the user's progress and performance metrics, while the interview menu allows users to initiate practice sessions and select their preferred settings. The history menu displays a record of past interviews, including questions asked, responses given, and feedback received. The settings menu enables users to customize their experience, adjusting parameters such as question types, difficulty levels, and AI model preferences. Finally, the help menu offers guidance on using the app effectively, including tips for preparing for interviews and troubleshooting common issues.
11. User login should be simple registration. 
12. design refers to references/app_design. The app's user interface is designed to be intuitive and user-friendly, ensuring that users can easily navigate through the various features and functionalities. The design incorporates visual elements that enhance the overall user experience, such as clear icons, responsive layouts, and visually appealing color schemes. Additionally, the app's design prioritizes accessibility, ensuring that users with different abilities can engage with the platform effectively.

## Technical Implementation
1. the app is built using FLASK + HTML+CSS. 
2. DB is supabase
3. the app uses OpenRouter for LLM integration, allowing users to select from various models and providers for their interview practice sessions. This flexibility ensures that users can choose the AI model that best aligns with their needs and preferences, enhancing the overall effectiveness of the app.
4. I also want to give it a try with local LLMs and decision models, such as QWEN, Ollama. I have RTX4070-TI 16GB. In the app configuration, one can select the model to use.
5. security: prompt injection should be prevented. Oher AI security issues should be considers based on OWASP top 10 AI security risks. It doesn't need to cover everything, but at least the most common ones.

## Project-related information
Project related information is given in docs/00-project-objective.md, and the project is based on the project description. The project is designed to be flexible and adaptable, allowing for easy integration with different AI models and providers. The app's architecture is modular, enabling users to customize their interview practice experience according to their specific needs and preferences. Additionally, the app incorporates best practices for AI security, ensuring that users can engage with the platform safely and confidently.



# available models from OpenRouter
Models available to you
basic
Claude 3 Haiku
Claude 3.5 Haiku
Claude Haiku 4.5
Claude Sonnet Latest
DeepSeek Flash Latest
DeepSeek V4 Flash 0731
DeepSeek V4 Flash Latest
DeepSeek V4.1 Flash
Gemini 2.5 Flash
Nano Banana (Gemini 2.5 Flash Image)
Gemini 2.5 Flash Lite
Gemini 3.8 Flash
Gemini 3.8 Flash Lite TTS
Gemini 3.8 Flash TTS
Gemini Flash Latest
Gemma 4 31B
MiniMax M2.7
GPT-3.5 Turbo
GPT-4.1 Mini
GPT-4.1 Nano
GPT-4o-mini
GPT-5 Mini
GPT-5 Nano
GPT-5.2
GPT-5.2-Codex
GPT-5.4
GPT-5.4 Mini
GPT-5.4 Nano
GPT-6 Luna
GPT-6 Luna (batch)
GPT Audio
GPT Audio Mini
GPT Mini Latest
Text Embedding 3 Large
Text Embedding 3 Small
Whisper Large V3 Turbo
Qwen3 Embedding 8B
Jev 1.13
Jev Latest
Models available to you
advanced
Claude 3 Haiku
Claude Haiku 4.5
Claude Opus 4.7
Claude Sonnet Latest
DeepSeek Flash Latest
DeepSeek V4 Flash 0423
DeepSeek V4 Flash 0731
DeepSeek V4 Flash Latest
DeepSeek V4 Pro 0423
DeepSeek V4 Pro 0813
DeepSeek V4.1 Flash
Gemini 2.5 Flash
Nano Banana (Gemini 2.5 Flash Image)
Gemini 2.5 Flash Lite
Nano Banana 2 (Gemini 3.1 Flash Image)
Gemini 3.1 Flash Lite
Gemini 3.5 Flash Lite
Gemini 3.7 Flash
Gemini 3.7 Flash (batch)
Gemini 3.8 Flash
Gemini 3.8 Flash Lite TTS
Gemini 3.8 Flash TTS
Gemini Flash Latest
Gemma 4 31B
MiniMax M2.7
GPT-3.5 Turbo
GPT-4.1 Mini
GPT-4.1 Nano
GPT-4o
GPT-4o (2024-11-20)
GPT-4o-mini
GPT-4o Mini Transcribe
GPT-5 Mini
GPT-5 Nano
GPT-5.2
GPT-5.2-Codex
GPT-5.4
GPT-5.4 Mini
GPT-5.4 Nano
GPT-5.5
GPT-5.6 Luna
GPT-5.6 Sol
GPT-5.6 Terra
GPT-6 Luna
GPT-6 Luna (batch)
GPT-6 Sol
GPT Audio
GPT Audio Mini
GPT Image 2.5 Flare
GPT Image 2.5 Sunburst
GPT Mini Latest
Text Embedding 3 Large
Text Embedding 3 Small
Whisper Large V3 Turbo
Sonar Deep Research
Qwen3 Embedding 8B
Rerank 4 Fast
Rerank 4 Pro
Jev 1.13
Jev Latest
Grok 4.5
GLM 5.2