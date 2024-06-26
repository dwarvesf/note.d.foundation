import os
import re
import duckdb
import argparse
import frontmatter
import gitignore_parser
import time
import subprocess
from dateutil import parser
from openai import OpenAI
import openai
from dotenv import load_dotenv
from datetime import timezone
import shutil
import requests
import json

load_dotenv()
openai_client = OpenAI()
ollama_openai_client = OpenAI(
    base_url=os.getenv("OLLAMA_OPENAI_BASE_URL"),
    api_key=os.getenv("OLLAMA_API_KEY"),
)


spr_compression_prompt = f"""
# MISSION
You are a Sparse Priming Representation (SPR) writer. An SPR is a particular kind of use of language for advanced NLP, NLU, and NLG tasks, particularly useful for the latest generation of Large Language Models (LLMs). You will be given information by the USER which you are to render as an SPR.

# THEORY
LLMs are a kind of deep neural network. They have been demonstrated to embed knowledge, abilities, and concepts, ranging from reasoning to planning, and even to theory of mind. These are called latent abilities and latent content, collectively referred to as latent space. The latent space of an LLM can be activated with the correct series of words as inputs, which will create a useful internal state of the neural network. This is not unlike how the right shorthand cues can prime a human mind to think in a certain way. Like human minds, LLMs are associative, meaning you only need to use the correct associations to "prime" another model to think in the same way.

# METHODOLOGY
Render the input as a distilled list of succinct statements, assertions, associations, concepts, analogies, and metaphors. The idea is to capture as much, conceptually, as possible but with as few words as possible. Write it in a way that makes sense to you, as the future audience will be another language model, not a human. Use complete sentences.
"""


def spr_compress(text):
    try:
        text = text.replace("\n", " ")
        if len(text) > 100:
            return openai_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": spr_compression_prompt,
                    },
                    {
                        "role": "user",
                        "content": text,
                    },
                ],
                model="gpt-3.5-turbo-0125",
            )
    except openai.BadRequestError:
        return openai_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": spr_compression_prompt,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            model="gpt-4-turbo",
        )
    except AttributeError:
        return None

    return None


def get_ollama_embeddings(bearer_token, model, prompt):
    url = f"{os.getenv('OLLAMA_BASE_URL')}/api/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {bearer_token}",
    }
    data = {"model": model, "prompt": prompt}

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code != 200:
        raise Exception(
            f"Request failed with status code {response.status_code}:\n{response.text}"
        )

    embeddings = response.json()
    return embeddings


def embed_custom(text):
    try:
        text = text.replace("\n", " ")
        if len(text) > 100:
            return get_ollama_embeddings(
                bearer_token=os.getenv("OLLAMA_API_KEY"),
                model="snowflake-arctic-embed:335m",
                prompt=text,
            )
    except AttributeError:
        return None

    return None


def embed_openai(text):
    try:
        text = text.replace("\n", " ")
        if len(text) > 100:
            return openai_client.embeddings.create(
                input=[text], model="text-embedding-3-small"
            )
    except openai.BadRequestError:
        spr_content = spr_compress(text)
        spr_content_text = (
            spr_content.choices[0].message.content if spr_content else None
        )
        return openai_client.embeddings.create(
            input=[spr_content_text], model="text-embedding-3-small"
        )
    except AttributeError:
        return None

    return None


def extract_frontmatter(file_path):
    with open(file_path, "r") as file:
        post = frontmatter.load(file)
        return post.metadata, post.content


def alter_columns(conn, frontmatter):
    # Detect column types
    column_types = {}
    for key, value in frontmatter.items():
        if isinstance(value, list):
            column_types[key] = "VARCHAR[]"
        elif isinstance(value, bool):
            column_types[key] = "BOOLEAN"
        elif isinstance(value, int):
            column_types[key] = "BIGINT"
        elif isinstance(value, float):
            column_types[key] = "DOUBLE"
        else:
            column_types[key] = "VARCHAR"

        if "embeddings_spr_custom" in key:
            column_types[key] = "FLOAT[1024]"
        if "embeddings_openai" in key:
            column_types[key] = "FLOAT[1536]"
        if "last_updated" in key:
            column_types[key] = "TIMESTAMP"
        if "tags" in key:
            column_types[key] = "VARCHAR[]"
        if "authors" in key:
            column_types[key] = "VARCHAR[]"
        if "draft" in key:
            column_types[key] = "BOOLEAN"
        if "date" in key:
            column_types[key] = "DATE"
        if "discord_id" in key:
            column_types[key] = "VARCHAR"

    # Add new columns if they don't already exist or update them
    for column, column_type in column_types.items():
        try:
            conn.execute(f"ALTER TABLE vault ADD COLUMN {column} {column_type}")
        except duckdb.ProgrammingError:
            pass

        try:
            conn.execute(f"ALTER TABLE vault ALTER COLUMN {column} TYPE {column_type}")
        except duckdb.duckdb.ConversionException:
            pass


def regenerate_embeddings(md_content, frontmatter, spr_content_text=""):
    # Generate an SPR for the md_content and embed it
    if not spr_content_text:
        spr_content = spr_compress(md_content)
        if spr_content:
            print(f"SPR: {spr_content}")
        spr_content_text = (
            spr_content.choices[0].message.content if spr_content else None
        )
    frontmatter["spr_content"] = spr_content_text

    # Generate embeddings for the SPR
    embeddings_spr_custom = embed_custom(spr_content_text)
    if embeddings_spr_custom:
        print(f"SPR Embeddings: {embeddings_spr_custom}")
    embeddings_spr_custom_values = (
        embeddings_spr_custom["embedding"] if embeddings_spr_custom else None
    )
    frontmatter["embeddings_spr_custom"] = embeddings_spr_custom_values

    # Generate OpenAI embeddings for the md_content
    embeddings_openai = embed_openai(md_content)
    if embeddings_openai:
        print(f"Embeddings: {embeddings_openai}")
    frontmatter["embeddings_openai"] = (
        embeddings_openai.data[0].embedding if embeddings_openai else None
    )
    frontmatter["total_tokens"] = (
        embeddings_openai.usage.total_tokens if embeddings_openai else 0
    )


def setup_frontmatter(md_content, frontmatter, short_path, file_path):
    # Set the frontmatter metadata to include path and content
    frontmatter["file_path"] = short_path
    frontmatter["md_content"] = md_content if md_content else None

    # Get the path to the submodule
    submodule_path = os.path.dirname(file_path)

    # Get the last updated date from Git
    last_updated = subprocess.check_output(
        ["git", "log", "-1", "--pretty=format:%ai"], cwd=submodule_path
    )
    last_updated = last_updated.decode("utf-8").rstrip()

    # Convert from 'yyyy-mm-dd hh:mm:ss +zzzz' to 'yyyy-mm-ddThh:mm:ss+zzzz'
    last_updated_dt = parser.parse(last_updated)
    last_updated = last_updated_dt.isoformat()
    frontmatter["last_updated"] = last_updated

    # Get estimated tokens from md_content
    estimated_tokens = len(md_content) // 4
    frontmatter["estimated_tokens"] = estimated_tokens

    # Check if the frontmatter key is a list represented  as a comma seperated string, convert it into a list
    if "tags" in frontmatter.keys() and isinstance(frontmatter["tags"], str):
        frontmatter["tags"] = frontmatter["tags"].split(",")

    if "authors" in frontmatter.keys() and isinstance(frontmatter["authors"], str):
        frontmatter["authors"] = frontmatter["authors"].split(",")


def add_to_database(conn, file_path, frontmatter, md_content):
    # Remove the root folder from file_path
    short_path = re.sub(r"^.*?/", "", file_path)

    # Setup the frontmatter metadata to include path and content
    setup_frontmatter(md_content, frontmatter, short_path, file_path)

    # Check if the file_path already exists in the database
    existing_row = conn.execute(
        "SELECT * FROM vault WHERE file_path = ? LIMIT 1", [short_path]
    ).fetch_arrow_table()

    if existing_row:
        # Check if the SPR content and openai embeddings exist and update them
        row_spr_content = (
            existing_row["spr_content"][0].as_py()
            if "spr_content" in existing_row.column_names
            else None
        )
        row_embeddings_spr_custom = (
            existing_row["embeddings_spr_custom"][0].as_py()
            if "embeddings_spr_custom" in existing_row.column_names
            else None
        )
        row_md_content = (
            existing_row["md_content"][0].as_py()
            if "md_content" in existing_row.column_names
            else None
        )

        if (
            not row_spr_content
            or not row_embeddings_spr_custom
            or row_md_content != md_content
        ):
            regenerate_embeddings(md_content, frontmatter, row_spr_content)

        alter_columns(conn, frontmatter)

        del frontmatter["file_path"]
        conn.execute(
            f"UPDATE vault SET {', '.join(f'{key} = ?' for key in frontmatter.keys())} WHERE file_path = ?",
            list(frontmatter.values()) + [short_path],
        )
        return

    regenerate_embeddings(md_content, frontmatter)
    alter_columns(conn, frontmatter)

    conn.execute(
        f"INSERT INTO vault ({', '.join(frontmatter.keys())}) VALUES ({', '.join('?' for _ in frontmatter.keys())})",
        list(frontmatter.values()),
    )


def get_changed_md_files(directory):
    try:
        changed_files = (
            subprocess.check_output(
                ["git", "diff", "--name-only", "HEAD^"],
                cwd=directory,
                stderr=subprocess.DEVNULL,  # Suppress stderr
            )
            .decode("utf-8")
            .splitlines()
        )
    except subprocess.CalledProcessError as e:
        error_message = e.output.decode("utf-8") if e.output else ""
        if "unknown revision or path not in the working tree" in error_message:
            try:
                # Handle the case when HEAD^ doesn't exist (e.g., first commit)
                changed_files = (
                    subprocess.check_output(
                        ["git", "diff", "--name-only", "HEAD"],
                        cwd=directory,
                        stderr=subprocess.DEVNULL,  # Suppress stderr
                    )
                    .decode("utf-8")
                    .splitlines()
                )
            except subprocess.CalledProcessError:
                # Handle the case when HEAD doesn't exist (no commits at all)
                changed_files = []
        else:
            raise
    return [f for f in changed_files if f.endswith(".md")]


def process_directory(conn, directory, limit, process_all):
    ignore_file_path = os.path.join(directory, ".export-ignore")
    if os.path.exists(ignore_file_path):
        spec = gitignore_parser.parse_gitignore(ignore_file_path)

    changed_md_files = []
    if not process_all:
        # Check for changes in the main repository
        changed_md_files += get_changed_md_files(directory)

        # Check for changes in each submodule
        try:
            submodules = (
                subprocess.check_output(
                    ["git", "submodule", "foreach", "--quiet", "echo $path"],
                    cwd=directory,
                    stderr=subprocess.DEVNULL,  # Suppress stderr
                )
                .decode("utf-8")
                .splitlines()
            )
            for submodule in submodules:
                submodule_path = os.path.join(directory, submodule)
                changed_md_files += [
                    os.path.join(submodule, f)
                    for f in get_changed_md_files(submodule_path)
                ]
        except subprocess.CalledProcessError:
            print(f"Failed to fetch submodule changes in {directory}")

    short_paths = []
    i = 0
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".md"):
                full_path = os.path.join(root, file)
                short_path = re.sub(r"^.*?/", "", full_path)
                short_paths.append(short_path)
                abs_path = os.path.abspath(full_path)
                if not spec(abs_path):
                    if process_all or short_path in changed_md_files:
                        frontmatter, md_content = extract_frontmatter(full_path)
                        if frontmatter:
                            print(f"Processing {full_path}...")
                            add_to_database(conn, full_path, frontmatter, md_content)
                            i += 1
                            if limit and i >= limit:
                                return
    # Remove old files
    print("Removing old file_paths...")
    results = conn.execute(
        f"DELETE FROM vault WHERE file_path NOT IN ({', '.join('?' for _ in short_paths)})",
        short_paths,
    ).fetchall()


def remove_unwanted_lines(file_path):
    # Define the lines to be removed
    lines_to_remove = [
        "CREATE SCHEMA information_schema;",
        "CREATE SCHEMA pg_catalog;",
    ]

    # Read the file
    with open(file_path, "r") as file:
        lines = file.readlines()

    # Write back only the lines that are not in the list to be removed
    with open(file_path, "w") as file:
        for line in lines:
            if line.strip() not in lines_to_remove:
                file.write(line)


def export(conn, format):
    output_dir = "db"
    match format:
        case "csv":
            conn.execute(f"EXPORT DATABASE '{output_dir}'")
        case "parquet":
            conn.execute(f"EXPORT DATABASE '{output_dir}' (FORMAT PARQUET)")

    # Path to the exported schema.sql file
    schema_file_path = os.path.join(output_dir, "schema.sql")

    # Remove unwanted lines from the schema.sql file
    if os.path.exists(schema_file_path):
        remove_unwanted_lines(schema_file_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", help="the directory to scan")
    parser.add_argument(
        "--format", choices=["csv", "parquet"], default="csv", help="output format"
    )
    parser.add_argument("--limit", type=int, help="limit the number of files processed")
    parser.add_argument(
        "--all", action="store_true", help="process all files, not just changed ones"
    )
    args = parser.parse_args()

    conn = duckdb.connect("vault.duckdb")

    # Check if the WAL file exists, export the database to be safe
    if os.path.exists("vault.duckdb.wal"):
        export(conn, args.format)

    try:
        conn.execute("IMPORT DATABASE 'db'")
    except duckdb.duckdb.CatalogException:
        pass

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vault (
            file_path TEXT,
            md_content TEXT,
            embeddings_openai FLOAT[1536],
            embeddings_spr_custom FLOAT[1024]
        )
        """
    )

    try:
        print(f"Processing {args.directory} to DuckDB...")
        process_directory(conn, args.directory, args.limit, args.all)
    except KeyboardInterrupt:
        shutil.copyfile("vault.duckdb", "vault.duckdb.bak")

    export(conn, args.format)
    conn.close()

    print("Database exported. Exiting...")


if __name__ == "__main__":
    main()
