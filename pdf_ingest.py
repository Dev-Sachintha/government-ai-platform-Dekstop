import io
import pgdb
import zipfile
import pypdf

def init_document_table(db_path: str):
    """Creates the government_services table for storing PDF text."""
    conn = pgdb.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS government_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            content TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

def ingest_zip_pdfs_to_sqlite(zip_path: str, db_path: str):
    """Extracts text from all PDFs inside the ZIP archive and inserts them into SQLite."""
    init_document_table(db_path)
    conn = pgdb.connect(db_path)
    cursor = conn.cursor()

    rows = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for filename in z.namelist():
            if filename.lower().endswith(".pdf") and not filename.startswith("__MACOSX"):
                with z.open(filename) as f:
                    try:
                        reader = pypdf.PdfReader(io.BytesIO(f.read()))
                        for page_num, page in enumerate(reader.pages, start=1):
                            text = page.extract_text()
                            if text and text.strip():
                                rows.append((filename, page_num, text.strip()))
                    except Exception as e:
                        print(f"Error processing {filename}: {e}")

    try:
        if not rows:
            raise ValueError("No extractable PDF text found; the existing documents were left untouched.")
        # Replace the documents atomically so other users never see an empty table.
        cursor.execute("DELETE FROM government_services;")
        cursor.executemany(
            "INSERT INTO government_services (filename, page_number, content) VALUES (?, ?, ?);", rows
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"Government service PDFs ingested into the database ({len(rows)} pages).")

if __name__ == "__main__":
    import os
    if os.path.exists("Downloads.zip"):
        ingest_zip_pdfs_to_sqlite("Downloads.zip", "database.db")
    else:
        print("Downloads.zip not found in current directory.")
