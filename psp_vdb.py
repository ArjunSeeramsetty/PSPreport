import pdfplumber
import pandas as pd
from PDFparser_Gemini import PDFParser
import os
import logging
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb
import json

# --- Configuration ---
PERSISTENT_DB_PATH = "./VDB/my_pdf_vector_db"
COLLECTION_NAME = "pdf_reports_collection"
MODEL_NAME = 'all-MiniLM-L6-v2'

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

pdf_path = "C:/Users/arjun/Desktop/PSPreport/sample input/19.04.25_NLDC_PSP.pdf"
parser = PDFParser()

if not os.path.exists(pdf_path):
    logger.error(f"PDF file not found: {pdf_path}")
    print(f"PDF file not found: {pdf_path}")
else:
    raw_tables, report_date = parser._extract_raw_tables(pdf_path)
    table_items = list(raw_tables.items())[1:]
    def serialize_tables_to_markdown(table_items):
        markdown_tables = []
        for key, table_df in table_items:
            if isinstance(table_df, pd.DataFrame):
                markdown_str = f"This is Table '{key}':\n"
                markdown_str += table_df.to_markdown(index=False)
                markdown_tables.append(markdown_str)
            else:
                markdown_tables.append(f"This is Table '{key}':\n(Not a DataFrame, type: {type(table_df)})")
        return markdown_tables
    textual_tables = serialize_tables_to_markdown(table_items)

    def extract_prose_from_pdf(pdf_path):
        all_prose = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_tables = page.find_tables()
                table_bboxes = [t.bbox for t in page_tables]
                def not_within_bboxes(obj): 
                    def obj_in_bbox(obj, bbox):
                        v_mid = (obj["top"] + obj["bottom"]) / 2
                        h_mid = (obj["x0"] + obj["x1"]) / 2
                        return (h_mid >= bbox[0] and h_mid <= bbox[2] and v_mid >= bbox[1] and v_mid <= bbox[3])
                    return not any(obj_in_bbox(obj, bbox) for bbox in table_bboxes)
                prose = page.filter(not_within_bboxes).extract_text()
                all_prose.append(prose)
        return "\n".join([p for p in all_prose if p])

    prose_text = extract_prose_from_pdf(pdf_path)

    # 1. Chunk the prose text
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    prose_chunks = text_splitter.split_text(prose_text)

    # 2. Create a unified list of documents with rich metadata
    all_docs = []
    metadata = []
    for i, chunk in enumerate(prose_chunks):
        all_docs.append(chunk)
        metadata.append({
            'source_pdf': pdf_path,
            'content_type': 'prose',
            'chunk_num': i
        })
    for i, table_str in enumerate(textual_tables):
        all_docs.append(table_str)
        metadata.append({
            'source_pdf': pdf_path,
            'content_type': 'table',
            'table_num': i + 1
        })
    ids = [f"doc_{i}" for i in range(len(all_docs))]

    # --- 1. Initialize Persistent Client and Model ---
    print(f"Initializing persistent client at: {PERSISTENT_DB_PATH}")
    client = chromadb.PersistentClient(path=PERSISTENT_DB_PATH)
    model = SentenceTransformer(MODEL_NAME)

    # --- 2. Get or Create the Collection ---
    print(f"Loading or creating collection: {COLLECTION_NAME}")
    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    # --- 3. Populate the DB ONLY IF IT'S EMPTY ---
    if collection.count() == 0:
        print("Collection is empty. Running the data ingestion and embedding process.")
        print("Generating embeddings...")
        embeddings = model.encode(all_docs, show_progress_bar=True)
        print("Adding documents to the collection...")
        collection.add(
            embeddings=embeddings.tolist(),
            documents=all_docs,
            metadatas=metadata,
            ids=ids
        )
        print("Database populated and saved.")
    else:
        print(f"Collection already contains {collection.count()} documents. Skipping population.")

    # --- 4. Query the Database (this works on both new and loaded DBs) ---
    print("\n--- Performing a search query ---")
    query = "what was the revenue?"
    query_embedding = model.encode([query])
    results = collection.query(
        query_embeddings=query_embedding.tolist(),
        n_results=2
    )
    print("Search Results:")
    print(json.dumps(results, indent=2))

    # Keep the console open
    import code
    code.interact(local=locals())