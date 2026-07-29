import os
import logging
import glob
from pathlib import Path
from datetime import datetime
from haystack import Document, Pipeline
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
from haystack.components.builders import PromptBuilder, ChatPromptBuilder
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.components.agents import Agent
from haystack.tools import PipelineTool
from haystack.dataclasses import ChatMessage
from haystack.components.generators.utils import print_streaming_chunk
from haystack.utils import Secret
from haystack.document_stores.types import DuplicatePolicy

# --- Elasticsearch & hybrid retriever components --- #
from haystack_integrations.document_stores.elasticsearch import ElasticsearchDocumentStore
from haystack_integrations.components.retrievers.elasticsearch import ElasticsearchBM25Retriever, ElasticsearchEmbeddingRetriever
from haystack.components.embedders import OpenAIDocumentEmbedder, OpenAITextEmbedder
from haystack.components.joiners import DocumentJoiner
from haystack.components.embedders import SentenceTransformersTextEmbedder, SentenceTransformersDocumentEmbedder


from haystack_experimental.chat_message_stores.in_memory import InMemoryChatMessageStore
from haystack_experimental.components.retrievers import ChatMessageRetriever
from haystack_experimental.components.writers import ChatMessageWriter


MIGRATE_PROJECT_NAME = "spring-petclinic-main"

with open("api_key.txt", "r") as f:
    API_KEY = f.read().strip()

chat_generator = OpenAIChatGenerator(
    model="gpt-4o-mini",
    api_key=Secret.from_token(API_KEY),
    generation_kwargs={"temperature": 0}
)

def load_and_index_data(document_store: ElasticsearchDocumentStore, embedder):
    es_docs = []
    embedder.warm_up()
    
    
    
    related_files = [
        # {"path": f"./rag_knowledge_base/pact/v3/fail", "category": "pact_failed_example"},
        {"path": f"./rag_knowledge_base/pact/v3/pass", "category": "pact_passed_example"},
        {"path": f"./rag_knowledge_base/karate", "category": "karate_specification"},
        # {"path": f"./monolith_features/{MIGRATE_PROJECT_NAME}_features.txt", "category": "monolithic_system_analysis"},
    ]
    
    for file_info in related_files:
        base_path = file_info["path"]
        category = file_info["category"]
        
        if os.path.exists(base_path):
            files_to_read = []
            
            if os.path.isdir(base_path):
                for root, dirs, files in os.walk(base_path):
                    for file in files:
                        files_to_read.append(os.path.join(root, file))
            else:
                files_to_read.append(base_path)
                
            for file_path in files_to_read:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        
                        doc = Document(
                            content=content,
                            meta={"file_name": file_path, "category": category}
                        )
                        es_docs.append(doc)
                        print(f"準備寫入 Elasticsearch: {file_path}")
                except Exception as e:
                    print(f"讀取檔案失敗 {file_path}, 錯誤原因: {e}")
        else:
            print(f"警告：找不到路徑 {base_path}")

    if es_docs:
        try:
            embedded_es = embedder.run(documents=es_docs)["documents"]
            document_store.write_documents(embedded_es)
            print(f"成功將 {len(es_docs)} 筆文件寫入 Elasticsearch！")
        except Exception as e:
            print(f"寫入 Elasticsearch 失敗, 錯誤原因: {e}")

def generate_test_case_by_BM25():
    document_store = ElasticsearchDocumentStore(
        hosts="http://localhost:9200",
        index=f"{MIGRATE_PROJECT_NAME}_migration_docs",
    )
    
    document_embedder =  SentenceTransformersDocumentEmbedder(model="sentence-transformers/all-MiniLM-L6-v2")
    try:
        document_store.delete_documents(document_ids=[doc.id for doc in document_store.filter_documents()])
    except Exception:
        pass
    
    load_and_index_data(document_store, document_embedder)

    es_pipeline = Pipeline()
    es_pipeline.add_component("text_embedder", SentenceTransformersTextEmbedder(model="sentence-transformers/all-MiniLM-L6-v2"))
    es_pipeline.add_component("bm25_retriever", ElasticsearchBM25Retriever(document_store=document_store, top_k=3))
    es_pipeline.add_component("vector_retriever", ElasticsearchEmbeddingRetriever(document_store=document_store, top_k=3))
    es_pipeline.add_component("document_joiner", DocumentJoiner(join_mode="reciprocal_rank_fusion"))
    es_pipeline.add_component("builder", PromptBuilder(template="Testing Examples:\n{% for doc in documents %}{{doc.content}}\n{% endfor %}"))
    
    es_pipeline.connect("text_embedder.embedding", "vector_retriever.query_embedding")
    es_pipeline.connect("bm25_retriever.documents", "document_joiner.documents")
    es_pipeline.connect("vector_retriever.documents", "document_joiner.documents")
    es_pipeline.connect("document_joiner.documents", "builder.documents")

    es_tool = PipelineTool(
        pipeline=es_pipeline,
        name="search_test_examples_tool",
        description="當你需要參考 Karate DSL 語法規範、Pact JSON 範例、或失敗/成功的測試合約對比時，使用此工具。",
        input_mapping={"query": ["bm25_retriever.query", "text_embedder.text"]},
        output_mapping={"builder.prompt": "retrieval_output"}
    )

    with open(f"./expected_microservice_endpoint/{MIGRATE_PROJECT_NAME}_expected_microservice_endpoints.yaml", "r", encoding="utf-8") as f:
        yaml_content = f.read()
    with open(f"./llm_analysis_result/{MIGRATE_PROJECT_NAME}_analysis_response.txt", "r", encoding="utf-8") as f:
        analysis_content = f.read()

    feature_contents = ""
    for f in Path(f"./karate_feature/{MIGRATE_PROJECT_NAME}").glob("*.feature"):
        feature_contents += f"\n=== {f.name} ===\n{open(f, 'r', encoding='utf-8').read()}"
    with open(f"./monolith_test_case_codes/{MIGRATE_PROJECT_NAME}_test_cases.txt", "r", encoding="utf-8") as f:
        test_cases = f.read()
    
    # 建立一個靜態 Pipeline，專門用來直接吐出這三個 Input
    static_input_pipeline = Pipeline()
    static_input_pipeline.add_component(
        "builder", 
        PromptBuilder(template=f"""
        [CRITICAL INPUT METADATA]
        1. Expected microservice endpoints YAML:
        {yaml_content}
        
        2. LLM analysis of legacy system's monolithic:
        {analysis_content}
        
        3. Existing Karate feature files:
        {feature_contents}
        
        4. Legacy system's test case:
        {test_cases}
        """)
    )

    static_input_tool = PipelineTool(
        pipeline=static_input_pipeline,
        name="get_migration_inputs_tool",
        description="【必用工具】在開始生成任何測試腳本前，必須先調用此工具來取得預期端點(YAML)、舊系統分析、以及現有 Karate 檔案內容作為基礎依賴。",
        input_mapping={}, # 不需要任何輸入參數
        output_mapping={"builder.prompt": "retrieval_output"}
    )
    
    message_store = InMemoryChatMessageStore()
    conversational_rag_agent = Pipeline()

    conversational_rag_agent.add_component(
        "agent",
        Agent(
            system_prompt="""
            You are a senior microservices migration expert. Your task is to generate new test scripts based on the user-provided "next service to migrate".
            
            You have two tools at your disposal:
            1. `get_migration_inputs_tool`: Use this to retrieve the critical background metadata, including expected microservice endpoints (YAML), legacy system analysis, existing Karate features, and legacy test cases.
            2. `search_test_examples_tool`: Use this to search and retrieve Karate DSL specifications, Pact JSON templates, or success/failure contract comparison examples via BM25 and Vector hybrid search.
            
            Please strictly follow these guidelines:
            1. INITIAL ACTION: Before generating any test scripts or analyzing the service, you MUST first call `get_migration_inputs_tool` to fetch the baseline migration metadata and dependencies.
            2. Generate Karate DSL (Feature file) that conforms to specifications.
            3. Generate corresponding Pact JSON (contract tests).
                - Every interaction MUST include a providerState.
                - Consumer and Provider MUST represent actual microservice names retrieved from the architecture features.
                - If the target service has no inter-service invocation relationship, DO NOT generate Pact JSON (ONLY generate Karate DSL).
            4. Maintain styling consistency with the examples found in the tools.
            
            CRITICAL CONSTRAINT:
            - DO NOT generate any conversational text, introductions, conclusions, or explanations. 
            - ONLY output the raw Karate DSL and Pact JSON. Any other text is strictly forbidden.
            """,
            chat_generator=chat_generator,
            tools=[es_tool, static_input_tool],
            streaming_callback=print_streaming_chunk,
        ),
    )

    conversational_rag_agent.add_component("message_retriever", ChatMessageRetriever(message_store))
    conversational_rag_agent.add_component("message_writer", ChatMessageWriter(message_store))

    conversational_rag_agent.connect("message_retriever.messages", "agent.messages")
    conversational_rag_agent.connect("agent.messages", "message_writer")

    chat_history_id = f"{MIGRATE_PROJECT_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    while True:
        question = input("\nPlease input the name of the next service to migrate (e.g., Order Service) or type Q to quit:\n🧑 ")
        if question.upper() == "Q":
            break
        if not question.strip():
            continue
        
        conversational_rag_agent.run(
            data={
                "message_retriever": {
                    "current_messages": [ChatMessage.from_user(question)],
                    "chat_history_id": chat_history_id,
                },
                "message_writer": {"chat_history_id": chat_history_id},
            }
        )
        
        
        
generate_test_case_by_BM25()