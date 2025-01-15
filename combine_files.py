import os

# Adjust to your actual base path if needed
BASE_PATH = r"C:\Projects\Jarvis\v0.2"

# Dictionary for the Backend mode
BACKEND_FILES = {
    "database.py": os.path.join(BASE_PATH, "backend", "database.py"),
    "main.py": os.path.join(BASE_PATH, "backend", "main.py"),
    "blocks.py": os.path.join(BASE_PATH, "backend", "agent", "blocks.py"),
    "orchestrator.py": os.path.join(BASE_PATH, "backend", "agent", "orchestrator.py"),
    "schemas.py": os.path.join(BASE_PATH, "backend", "agent", "schemas.py"),
}

# Dictionary for the Frontend mode
FRONTEND_FILES = {
    "App.tsx": os.path.join(BASE_PATH, "frontend", "App.tsx"),
    "HomeScreen.tsx": os.path.join(BASE_PATH, "frontend", "screens", "HomeScreen.tsx"),
    "SettingsScreen.tsx": os.path.join(BASE_PATH, "frontend", "screens", "SettingsScreen.tsx"),
}

# Dictionary for the custom mode: we want orchestrator.py, blocks.py, schemas.py,
# plus plan_prompt.md (which must be last).
# We'll keep plan_prompt.md separate so we can ensure it's appended last.
CUSTOM_FILES = {
    "orchestrator.py": os.path.join(BASE_PATH, "backend", "agent", "orchestrator.py"),
    "blocks.py": os.path.join(BASE_PATH, "backend", "agent", "blocks.py"),
    "schemas.py": os.path.join(BASE_PATH, "backend", "agent", "schemas.py"),
    # We'll handle plan_prompt.md outside this dictionary so it always goes last.
}
PLAN_PROMPT_MD = os.path.join(BASE_PATH, "backend", "agent", "prompts", "plan_prompt.md")

def get_folder_structure(mode: str) -> str:
    """
    Returns a concise folder structure string that includes only
    the relevant files for the given mode.
    """
    indent = "    "
    if mode == "backend":
        return (
            "v0.2/\n"
            + f"{indent}backend/\n"
            + f"{indent}{indent}database.py\n"
            + f"{indent}{indent}main.py\n"
            + f"{indent}{indent}agent/\n"
            + f"{indent}{indent}{indent}blocks.py\n"
            + f"{indent}{indent}{indent}orchestrator.py\n"
            + f"{indent}{indent}{indent}schemas.py\n"
        )
    elif mode == "frontend":
        return (
            "v0.2/\n"
            + f"{indent}frontend/\n"
            + f"{indent}{indent}App.tsx\n"
            + f"{indent}{indent}screens/\n"
            + f"{indent}{indent}{indent}HomeScreen.tsx\n"
            + f"{indent}{indent}{indent}SettingsScreen.tsx\n"
        )
    elif mode == "both":
        # Show all relevant files for backend + frontend
        return (
            "v0.2/\n"
            + f"{indent}backend/\n"
            + f"{indent}{indent}database.py\n"
            + f"{indent}{indent}main.py\n"
            + f"{indent}{indent}agent/\n"
            + f"{indent}{indent}{indent}blocks.py\n"
            + f"{indent}{indent}{indent}orchestrator.py\n"
            + f"{indent}{indent}{indent}schemas.py\n"
            + "\n"
            + f"{indent}frontend/\n"
            + f"{indent}{indent}App.tsx\n"
            + f"{indent}{indent}screens/\n"
            + f"{indent}{indent}{indent}HomeScreen.tsx\n"
            + f"{indent}{indent}{indent}SettingsScreen.tsx\n"
        )
    else:
        # Custom mode: orchestrator.py, blocks.py, schemas.py, plan_prompt.md
        return (
            "v0.2/\n"
            + f"{indent}backend/\n"
            + f"{indent}{indent}agent/\n"
            + f"{indent}{indent}{indent}orchestrator.py\n"
            + f"{indent}{indent}{indent}blocks.py\n"
            + f"{indent}{indent}{indent}schemas.py\n"
            + f"{indent}{indent}{indent}prompts/\n"
            + f"{indent}{indent}{indent}{indent}plan_prompt.md\n"
        )

def get_system_prompt() -> str:
    """
    Customize or replace this with whatever system-level instruction you want
    at the very beginning of your prompt.
    """
    return (
        "You are ChatGPT, a helpful developer assistant. You have been provided "
        "with a subset of files from the Jarvis project. Use this context for "
        "answering any user questions about the code. Do not reveal sensitive "
        "information or partial content that was not provided.\n"
    )

def gather_files(mode: str) -> list:
    """
    Given the mode (“backend”, “frontend”, “both”, or “custom”),
    return a list of tuples [(filename, path), ...] for the relevant files.

    For 'custom', we always put plan_prompt.md at the end.
    """
    if mode == "backend":
        files = list(BACKEND_FILES.items())  # -> [("database.py", "C:/...database.py"), ...]
    elif mode == "frontend":
        files = list(FRONTEND_FILES.items())
    elif mode == "both":
        # Merge both dictionaries
        merged = {}
        merged.update(BACKEND_FILES)
        merged.update(FRONTEND_FILES)
        files = list(merged.items())
    else:
        # Custom mode
        custom_list = list(CUSTOM_FILES.items())
        # Insert plan_prompt.md last
        custom_list.append(("plan_prompt.md", PLAN_PROMPT_MD))
        files = custom_list

    return files

def combine_files(mode: str, output_filename: str = "combined_prompt.txt"):
    """
    Creates a single text file that contains:
      1. A custom system prompt
      2. A limited folder structure (only relevant to the chosen mode)
      3. The concatenated contents of each file in the chosen mode
    """
    system_text = get_system_prompt()
    folder_structure = get_folder_structure(mode)
    files_to_combine = gather_files(mode)

    with open(output_filename, "w", encoding="utf-8") as out:
        # 1) Write the system prompt
        out.write("=== SYSTEM PROMPT ===\n")
        out.write(system_text.strip())
        out.write("\n\n")

        # 2) Write the folder structure
        out.write("=== FOLDER STRUCTURE (SELECTED) ===\n")
        out.write(folder_structure.strip())
        out.write("\n\n")

        # 3) Write the files
        out.write("=== FILE CONTENTS ===\n")
        for fname, fpath in files_to_combine:
            out.write(f"\n--- {fname} ---\n")
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    out.write(f.read())
            except Exception as e:
                out.write(f"[Error reading {fpath}: {e}]")

if __name__ == "__main__":
    print("Which files do you want to combine?")
    print("1) Backend only")
    print("2) Frontend only")
    print("3) Both backend and frontend")
    print("4) Custom selection (orchestrator.py, blocks.py, schemas.py, plan_prompt.md)")
    choice = input("Enter 1, 2, 3, or 4: ").strip()

    if choice == "1":
        mode = "backend"
    elif choice == "2":
        mode = "frontend"
    elif choice == "3":
        mode = "both"
    else:
        mode = "custom"

    combine_files(mode)
    print(f"Done! Created 'combined_prompt.txt' for mode: {mode}")
