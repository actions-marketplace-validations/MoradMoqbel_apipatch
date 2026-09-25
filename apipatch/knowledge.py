"""
ApiPatch Authoritative Migration Knowledge Base
Provides exact, up-to-date SDK migration rules, official code patterns, and modern replacements
for major third-party libraries across Python, JavaScript, TypeScript, and more.
This ensures the AI agent always migrates to 100% working, modern official SDK implementations
without hallucinations or placeholder exceptions.
"""

from typing import List, Dict, Set, Optional, Any


# Authoritative, verified migration knowledge for major ecosystems
MIGRATION_KNOWLEDGE_BASE: Dict[str, Dict[str, Any]] = {
    "google": {
        "aliases": ["google", "google-genai", "google.genai", "google-generativeai", "gemini", "generativelanguage"],
        "description": "Google GenAI SDK (google.genai) and Gemini 3 / Nano Banana Image Generation",
        "guidance": """\
• Google GenAI Migration Guidelines (Legacy google-generativeai → Modern google-genai):
  - Deprecated SDK: 'google-generativeai' is deprecated. Migrate to official 'google-genai' SDK.
  - Import Migration:
      OLD: import google.generativeai as genai
      NEW: from google import genai
           from google.genai import types
  - Initialization Migration:
      OLD: genai.configure(api_key=...)
      NEW: client = genai.Client(api_key=...)
  - Generation Migration:
      OLD: model = genai.GenerativeModel('gemini-1.5-pro')
           response = model.generate_content(prompt_or_contents)
      NEW: response = client.models.generate_content(
               model='gemini-1.5-pro',
               contents=prompt_or_contents
           )
  - Asynchronous Generation:
      NEW: response = await client.aio.models.generate_content(model='...', contents=...)
  - File API Migration:
      OLD: video_file = genai.upload_file(path=video_path, display_name=...)
           video_file = genai.get_file(video_file.name)
           genai.delete_file(video_file.name)
      NEW: video_file = client.files.upload(file=video_path, config=dict(display_name=...))
           video_file = client.files.get(name=video_file.name)
           client.files.delete(name=video_file.name)
  - Model Listing:
      OLD: genai.list_models()
      NEW: client.models.list()
  - Embeddings:
      OLD: genai.embed_content(model=..., content=...)
      NEW: client.models.embed_content(model=..., contents=...)
  - Image Generation & Editing (Nano Banana / Gemini 3 Image):
      Official Models: 'gemini-3.1-flash-image', 'gemini-3-pro-image', 'gemini-3.1-flash-lite-image', 'gemini-2.5-flash-image'
      Usage:
          response = client.models.generate_content(
              model="gemini-3.1-flash-image",
              contents=[prompt],
              config=types.GenerateContentConfig(
                  response_modalities=["IMAGE"],
                  response_format={"image": {"aspect_ratio": "16:9"}}
              )
          )
          for part in response.parts:
              if part.inline_data is not None:
                  image = part.as_image()
                  image.save("output.png")
  - NEVER use raw deprecated REST endpoints or raise NotImplementedError when updating Gemini code; migrate directly to google.genai Client.
"""
    },

    "openai": {
        "aliases": ["openai"],
        "description": "OpenAI Python & TypeScript Modern SDKs",
        "guidance": """\
• OpenAI v1.0+ Modern SDK Guidelines (and 2025/2026 Responses API):
  - Python Initialization: from openai import OpenAI; client = OpenAI(api_key=...)
  - Chat Completions: client.chat.completions.create(model="gpt-4o", messages=[...])
  - Responses API: client.responses.create(model="...", input=[...], max_output_tokens=...) with response.output_text is the official modern Responses API. NEVER convert Responses API to Chat Completions!
  - Modern Parameters: role: "developer" and max_completion_tokens / max_output_tokens are standard modern parameters. Do NOT revert them to "system" or max_tokens.
  - Embeddings: client.embeddings.create(model="text-embedding-3-small", input=...)
  - Response parsing: Access via attributes (e.g. response.choices[0].message.content, response.output_text).
  - TS/JS Initialization: import OpenAI from 'openai'; const client = new OpenAI({ apiKey: ... });
  - ONLY migrate genuinely legacy v0.x calls (e.g. openai.ChatCompletion.create, openai.Completion.create, openai.api_key = ...).
"""
    },

    "langchain": {
        "aliases": ["langchain", "langchain-core", "langchain-community", "langchain-openai", "langchain-anthropic", "langgraph"],
        "description": "LangChain v0.2 / v0.3+ and LangGraph LCEL Modernization",
        "guidance": """\
• LangChain v0.3+ Enterprise Migration Guidelines:
  - Partner Package Imports (MANDATORY in v0.3):
      OLD: from langchain.chat_models import ChatOpenAI
      NEW: from langchain_openai import ChatOpenAI
      OLD: from langchain.chat_models import ChatAnthropic
      NEW: from langchain_anthropic import ChatAnthropic
      OLD: from langchain.embeddings import OpenAIEmbeddings
      NEW: from langchain_openai import OpenAIEmbeddings
      OLD: from langchain.document_loaders import TextLoader, PyPDFLoader
      NEW: from langchain_community.document_loaders import TextLoader, PyPDFLoader
      OLD: from langchain.vectorstores import Chroma, FAISS
      NEW: from langchain_community.vectorstores import Chroma, FAISS (or from langchain_chroma import Chroma)
  - Core Schemas & Messages:
      from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
      from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
      from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
  - Deprecated Chains & LCEL Migration:
      OLD: from langchain.chains import LLMChain
           chain = LLMChain(llm=llm, prompt=prompt)
           output = chain.run(topic="AI")
      NEW: chain = prompt | llm | StrOutputParser()
           output = chain.invoke({"topic": "AI"})
  - Deprecated RetrievalQA:
      OLD: from langchain.chains import RetrievalQA; qa = RetrievalQA.from_chain_type(...)
      NEW: from langchain.chains import create_retrieval_chain
           from langchain.chains.combine_documents import create_stuff_documents_chain
           combine_docs_chain = create_stuff_documents_chain(llm, prompt)
           retrieval_chain = create_retrieval_chain(retriever, combine_docs_chain)
  - Deprecated Agent Initialization:
      OLD: from langchain.agents import initialize_agent, AgentType
      NEW: from langchain.agents import create_tool_calling_agent, AgentExecutor
           or from langgraph.prebuilt import create_react_agent
  - Execution Method:
      ALWAYS migrate '.run(...)' and '.__call__(...)' to '.invoke(...)'.
      Use '.batch([...])' for parallel inputs and '.stream(...)'.
"""
    },

    "anthropic": {
        "aliases": ["anthropic", "@anthropic-ai/sdk", "claude"],
        "description": "Anthropic Claude Modern Messages API & Structured Tool Use (v0.30 - v0.40+)",
        "guidance": """\
• Anthropic Claude 2026 Modern Messages API Guidelines:
  - Client Initialization:
      from anthropic import Anthropic, AsyncAnthropic
      client = Anthropic(api_key=...)
  - Standard Messages Call (Replacing legacy completion()):
      OLD: response = client.completion(prompt=f"{HUMAN_PROMPT} Hello{AI_PROMPT}", model="claude-2")
      NEW: response = client.messages.create(
               model="claude-3-5-sonnet-20241022",
               max_tokens=2048,
               messages=[{"role": "user", "content": "Hello"}]
           )
           text = response.content[0].text
  - Structured Tool Use (Function Calling):
      tools = [{
          "name": "lookup_data",
          "description": "Queries enterprise knowledge database",
          "input_schema": {
              "type": "object",
              "properties": {
                  "query": {"type": "string", "description": "Search keyword"}
              },
              "required": ["query"]
          }
      }]
      response = client.messages.create(
          model="claude-3-5-sonnet-20241022",
          max_tokens=2048,
          tools=tools,
          messages=[{"role": "user", "content": user_input}]
      )
  - Streaming Context Manager:
      with client.messages.stream(
          model="claude-3-5-sonnet-20241022",
          max_tokens=1024,
          messages=[{"role": "user", "content": prompt}]
      ) as stream:
          for text in stream.text_stream:
              print(text, end="", flush=True)
  - Preferred Models: 'claude-3-5-sonnet-20241022', 'claude-3-7-sonnet-20250219', 'claude-3-5-haiku-20241022'
"""
    },

    "dotenv": {
        "aliases": ["dotenv", "python-dotenv", "python_dotenv"],
        "description": "Python Dotenv (python-dotenv)",
        "guidance": """\
• Python-Dotenv Guidelines:
  - Import: 'from dotenv import load_dotenv' or 'import dotenv'
  - Standard Usage: 'load_dotenv()' is the official, fully supported method.
  - DO NOT replace 'load_dotenv()' with 'dotenv_values()' or manual os.environ dictionary loops.
  - Leave 'load_dotenv()' untouched if it is already present.
"""
    },

    "fastapi": {
        "aliases": ["fastapi"],
        "description": "FastAPI Lifespan Events Modernization",
        "guidance": """\
• FastAPI Modern Guidelines:
  - Replace deprecated '@app.on_event("startup")' and '@app.on_event("shutdown")' with lifespan context manager:
      @asynccontextmanager
      async def lifespan(app: FastAPI):
          # startup logic
          yield
          # shutdown logic
      app = FastAPI(lifespan=lifespan)
"""
    },

    "pydantic": {
        "aliases": ["pydantic", "pydantic-core", "pydantic-settings"],
        "description": "Pydantic v2 Modern Migration (ConfigDict, field_validator, model_dump)",
        "guidance": """\
• Pydantic v2 Migration Guidelines:
  - Configuration Migration:
      OLD: class Config:
               orm_mode = True
               allow_population_by_field_name = True
      NEW: from pydantic import ConfigDict
           model_config = ConfigDict(from_attributes=True, populate_by_name=True)
  - Validators Migration:
      OLD: from pydantic import validator
           @validator('name')
           def check_name(cls, v): return v
      NEW: from pydantic import field_validator
           @field_validator('name')
           @classmethod
           def check_name(cls, v): return v
  - Serialization:
      OLD: user.dict(), user.json()
      NEW: user.model_dump(), user.model_dump_json()
  - Settings Management:
      OLD: from pydantic import BaseSettings
      NEW: from pydantic_settings import BaseSettings
"""
    }
}


from apipatch.doc_hunter import DocHunter


def get_relevant_knowledge(
    detected_libraries: Optional[List[str]] = None,
    file_content: Optional[str] = None
) -> str:
    """
    Extracts authoritative, focused migration instructions and live package documentation
    for the libraries actively detected in the target file or project.
    """
    selected_guidance: List[str] = []
    matched_keys: Set[str] = set()

    # Collect search tokens
    tokens: Set[str] = set()
    raw_libs: List[str] = list(detected_libraries or [])
    if detected_libraries:
        for lib in detected_libraries:
            tokens.add(lib.lower().strip())
            if '/' in lib:
                tokens.add(lib.split('/')[1].lower().strip())

    if file_content:
        lower_code = file_content.lower()
        for key, entry in MIGRATION_KNOWLEDGE_BASE.items():
            for alias in entry["aliases"]:
                if alias in lower_code or alias.replace('-', '_') in lower_code:
                    tokens.add(key)
                    break

    for key, entry in MIGRATION_KNOWLEDGE_BASE.items():
        if key in tokens or any(alias in tokens for alias in entry["aliases"]):
            if key not in matched_keys:
                matched_keys.add(key)
                selected_guidance.append(entry["guidance"])

    knowledge_text = ""
    if selected_guidance:
        knowledge_text = "### 📚 Authoritative Modern SDK Migration Rules:\n" + "\n".join(selected_guidance)

    # Append live package grounding from DocHunter
    if raw_libs:
        live_grounding = DocHunter.build_grounded_context(raw_libs)
        if live_grounding:
            if knowledge_text:
                knowledge_text += "\n\n" + live_grounding
            else:
                knowledge_text = live_grounding

    return knowledge_text
