# backend/vectorstore.py

import os
from dotenv import load_dotenv
load_dotenv()

import chromadb
from chromadb import PersistentClient

from langchain_openai.embeddings import OpenAIEmbeddings
try:
    from langchain_community.text_splitter import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

openai_api_key = os.getenv("OPENAI_API_KEY")

# Initialize embeddings
embedding_model = OpenAIEmbeddings(openai_api_key=openai_api_key)

# Use new approach for Chroma
client = PersistentClient(path="chroma_store")

try:
    collection = client.get_collection("doc_chunks")
except:
    collection = client.create_collection("doc_chunks")

def ingest_document(doc_id: int, text_content: str):
    if not text_content.strip():
        print(f"[ingest_document] doc_id={doc_id}, no text -> skip")
        return

    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_text(text_content)
    print(f"[ingest_document] doc_id={doc_id}, #chunks={len(chunks)}")

    embeddings = embedding_model.embed_documents(chunks)
    doc_ids = [f"{doc_id}-chunk{i}" for i in range(len(chunks))]
    metadatas = [{"doc_id": str(doc_id), "chunk_index": i} for i in range(len(chunks))]

    collection.add(documents=chunks, embeddings=embeddings, ids=doc_ids, metadatas=metadatas)
    print(f"[ingest_document] doc_id={doc_id} => DONE")

def query_docs(query: str, top_k: int = 3):
    if not query.strip():
        return []
    query_embedding = embedding_model.embed_query(query)
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)

    found_chunks = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    for i in range(len(docs)):
        found_chunks.append({
            "chunk_text": docs[i],
            "metadata": metas[i],
            "distance": dists[i]
        })
    return found_chunks
