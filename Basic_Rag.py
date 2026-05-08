from langchain_openai import ChatOpenAI,OpenAIEmbeddings
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.tools import tool


class RAGPDF:
    def __init__(self, filepath:str):
        load_dotenv()
        llm = ChatOpenAI(model = "gpt-4o-mini")

        loader = PyPDFLoader(filepath)
        docs = loader.load()

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(docs)
        embedding_model = OpenAIEmbeddings(model='text-embedding-3-small')
        self.vector_store = FAISS.from_documents(chunks,embedding_model)
        self.retriever = self.vector_store.as_retriever(search_type='similarity',search_kwargs={'k':4})

    def get_tool(self):

        @tool
        def rag_tool(query):
            """
            Consult the uploaded documents and books for specific factual information.
            
            USE THIS TOOL IF:
            1. The user explicitly mentions 'documents', 'books', 'files', or 'uploaded content'.
            2. The user asks to answer 'factually' or 'based on the source'.
            3. The user asks a technical question likely contained in the specific PDF.
            
            OTHERWISE:
            If the user asks general questions, greetings, or common knowledge without 
            referencing the documents, respond using your internal knowledge.
            """
            result = self.retriever.invoke(query)
            context = [doc.page_content for doc in result]
            metadata = [doc.metadata for doc in result]

            return {
                'query': query,
                'context': context,
                'metadata': metadata

            }
        return rag_tool
    
