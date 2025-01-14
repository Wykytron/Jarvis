import os

# Change this to your actual project path if needed.
BASE_PATH = r"C:\Projects\Jarvis\v0.2"

# We define which files to include for each “mode.”
BACKEND_FILES = {
    "database.py": os.path.join(BASE_PATH, "backend", "database.py"),
    "main.py": os.path.join(BASE_PATH, "backend", "main.py"),
    "blocks.py": os.path.join(BASE_PATH, "backend", "agent", "blocks.py"),
    "orchestrator.py": os.path.join(BASE_PATH, "backend", "agent", "orchestrator.py"),
    "schemas.py": os.path.join(BASE_PATH, "backend", "agent", "schemas.py"),
}

FRONTEND_FILES = {
    "App.tsx": os.path.join(BASE_PATH, "frontend", "App.tsx"),
    "HomeScreen.tsx": os.path.join(BASE_PATH, "frontend", "screens", "HomeScreen.tsx"),
    "SettingsScreen.tsx": os.path.join(BASE_PATH, "frontend", "screens", "SettingsScreen.tsx"),
}

# A small helper that returns the relevant folder structure for each “mode.”
def get_folder_structure(mode: str) -> str:
    """
    Returns a concise folder structure string that includes only
    the relevant files for the given mode.
    """
    # Common indentation for readability:
    indent = "    "

    # Base structure (only show what matters for these files)
    base = [
        "v0.2/",
        f"{indent}backend/",
        f"{indent}{indent}database.py",
        f"{indent}{indent}main.py",
        f"{indent}{indent}agent/",
        f"{indent}{indent}{indent}blocks.py",
        f"{indent}{indent}{indent}orchestrator.py",
        f"{indent}{indent}{indent}schemas.py",
        "",
        f"{indent}frontend/",
        f"{indent}{indent}App.tsx",
        f"{indent}{indent}screens/",
        f"{indent}{indent}{indent}HomeScreen.tsx",
        f"{indent}{indent}{indent}SettingsScreen.tsx",
    ]
    # Convert to string
    full_structure = "\n".join(base)

    if mode == "backend":
        # Return only backend portion
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
        # Return only frontend portion
        return (
            "v0.2/\n"
            + f"{indent}frontend/\n"
            + f"{indent}{indent}App.tsx\n"
            + f"{indent}{indent}screens/\n"
            + f"{indent}{indent}{indent}HomeScreen.tsx\n"
            + f"{indent}{indent}{indent}SettingsScreen.tsx\n"
        )
    else:
        # “both” – return everything (backend + frontend)
        return full_structure


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


def gather_files(mode: str) -> dict:
    """
    Given the mode (“backend”, “frontend”, or “both”), return a dict of {filename: path}
    for the relevant files.
    """
    selected = {}
    if mode in ("backend", "both"):
        selected.update(BACKEND_FILES)
    if mode in ("frontend", "both"):
        selected.update(FRONTEND_FILES)

    return selected


def combine_files(mode: str, output_filename: str = "combined_prompt.txt"):
    """
    Creates a single text file that contains:
      1. A custom system prompt
      2. A limited folder structure (only relevant to the chosen mode)
      3. The concatenated contents of each file in the chosen mode
    """
    # 1. Grab system prompt text
    system_text = get_system_prompt()

    # 2. Grab folder structure
    folder_structure = get_folder_structure(mode)

    # 3. Get the dictionary of files (filename -> absolute path)
    files_to_combine = gather_files(mode)

    with open(output_filename, "w", encoding="utf-8") as out:
        # Write the system prompt
        out.write("=== SYSTEM PROMPT ===\n")
        out.write(system_text.strip())
        out.write("\n\n")

        # Write the folder structure
        out.write("=== FOLDER STRUCTURE (SELECTED) ===\n")
        out.write(folder_structure.strip())
        out.write("\n\n")

        # Write the files
        out.write("=== FILE CONTENTS ===\n")
        for fname, fpath in files_to_combine.items():
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
    choice = input("Enter 1, 2, or 3: ").strip()

    if choice == "1":
        mode = "backend"
    elif choice == "2":
        mode = "frontend"
    else:
        mode = "both"

    # Generate the combined prompt file
    combine_files(mode, output_filename="combined_prompt.txt")
    print(f"Done! Created 'combined_prompt.txt' for mode: {mode}")
