from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types
from github import Github,Auth
from dotenv import load_dotenv
import anthropic
import asyncio
import os
from audit import AuditLogger

load_dotenv()
g = Github(auth=Auth.Token(os.getenv("GITHUB_TOKEN")))
audit = AuditLogger()

REVIEW_SYSTEM_PROMPT = """
You are a senior engineer reviewing code for an AI Hotel Front Desk Agent 
system called AAVGO. This system combines VAPI for real time voice AI, 
HeyGen for interactive avatar with lip sync, Next.js for the frontend 
kiosk interface, N8N for backend automation, and TensorFlow.js for 
face detection.

This is a real time guest facing system running in a hotel lobby.
Failures are visible to guests immediately.

Evaluate every PR against these criteria:

CRITICAL — these break the guest experience:
- Missing VAPI session cleanup — sessions accumulate and exhaust connection limits
- No error handling when VAPI connection drops mid conversation
- Avatar stream starting before VAPI audio is ready — causes lip sync desync
- No fallback when HeyGen streaming fails — guest sees frozen avatar
- TensorFlow.js inference running on every animation frame without throttling
- Not disposing TensorFlow tensors after use — memory leak on long running kiosk
- Synchronous waits for N8N webhook responses in the guest flow
- Missing timeouts on N8N webhook calls — entire flow hangs if N8N is down

PERFORMANCE — flag with severity:
- Large components not using dynamic imports
- Sequential VAPI and HeyGen initialization that could be parallelized
- Unnecessary re-renders during active voice sessions
- Missing loading states during initialization

CODE QUALITY — flag as suggestions:
- Code placed in wrong directories per project structure guidelines
- Hardcoded API keys or tokens that should be in .env.local
- Missing TypeScript types on VAPI event handlers or HeyGen responses
- No error boundary around avatar or voice components
- Excessive complexity in any function over 50 lines long — suggest refactor
- Lack of comments explaining non-obvious engineering decisions
- Inconsistent code formatting or style that doesn't match the rest of the codebase
- Use of Emoji in code comments that may not be universally understood, Remove them or replace with clear language

OUTPUT FORMAT:
SUMMARY:
One paragraph overview of the PR and overall risk level.

ISSUES FOUND:
[SEVERITY] — Short title
File: filename line X
Problem: What is wrong
Guest Impact: What the guest experiences when this fails
Fix: Corrected code
Learning Note: Plain English explanation of the engineering principle

WHAT LOOKS GOOD:
Specific things done well

BEFORE MERGING:
Numbered list of blocking issues
"""

app = Server("jr-swe-agent")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="read_file",
            description="Reads a file from the codebase",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"}
                },
                "required": ["path"]
            }
        ),
        types.Tool(
            name="list_directory",
            description="Lists all files and folders in a directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to list"}
                },
                "required": ["path"]
            }
        ),
        types.Tool(
            name="search_files",
            description="Searches for files matching a pattern in a directory",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root directory to search"},
                    "pattern": {"type": "string", "description": "Filename pattern to match"}
                },
                "required": ["path", "pattern"]
            }
        ),
        types.Tool(
            name="get_repo",
            description="Gets information about a GitHub repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Owner of the repository"},
                    "repo": {"type": "string", "description": "Name of the repository"}
                },
                "required": ["owner", "repo"]
            }
        ),
        types.Tool(
            name="get_pull_request",
            description="Gets the details and diff of a pull request",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Owner of the repository"},
                    "repo": {"type": "string", "description": "Name of the repository"},
                    "pr_number": {"type": "integer", "description": "Pull request number"}
                },
                "required": ["owner", "repo", "pr_number"]
            }
        ),
        types.Tool(
            name="list_pull_requests",
            description="Lists open pull requests in a GitHub repository",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Owner of the repository"},
                    "repo": {"type": "string", "description": "Name of the repository"}
                },
                "required": ["owner", "repo"]
            }
        ),
        types.Tool(
            name="review_pull_request",
            description="ALWAYS use this tool when asked to review a PR. Fetches the PR diff AND runs a full structured code review with audit logging. Do not use get_pull_request for reviews.",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Owner of the repository"},
                    "repo": {"type": "string", "description": "Name of the repository"},
                    "pr_number": {"type": "integer", "description": "Pull request number"}
                },
                "required": ["owner", "repo", "pr_number"]
            }
        ),
        types.Tool(
            name="get_audit_log",
            description="Returns the audit log for the current session showing every decision made",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_only": {
                        "type": "boolean",
                        "description": "If true, only return current session. If false, return all history"
                    }
                },
                "required": []
            }
        ),
        types.Tool(
            name="approve_review",
            description="Mark a review as approved or rejected with your notes. This closes the audit entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "approved": {"type": "boolean", "description": "Whether you approve the PR"},
                    "notes": {"type": "string", "description": "Your reasoning for approving or rejecting"}
                },
                "required": ["approved", "notes"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    
    if name == "read_file":
        with open(arguments["path"]) as f:
            content = f.read()
        audit.log("read_file", arguments, content)
        return [types.TextContent(type="text", text=content)]

    elif name == "list_directory":
        import os as _os
        entries = _os.listdir(arguments["path"])
        result = "\n".join(entries)
        audit.log("list_directory", arguments, result)
        return [types.TextContent(type="text", text=result)]

    elif name == "search_files":
        import os as _os
        matches = []
        for root, dirs, files in _os.walk(arguments["path"]):
            dirs[:] = [d for d in dirs if d not in ['.venv', 'node_modules', '.git', '.next']]
            for file in files:
                if arguments["pattern"] in file:
                    matches.append(_os.path.join(root, file))
        result = "\n".join(matches)
        audit.log("search_files", arguments, result)
        return [types.TextContent(type="text", text=result)]

    elif name == "get_repo":
        repo = g.get_repo(f"{arguments['owner']}/{arguments['repo']}")
        info = f"Name: {repo.name}\nDescription: {repo.description}\nLanguage: {repo.language}\nStars: {repo.stargazers_count}\nDefault Branch: {repo.default_branch}"
        audit.log("get_repo", arguments, info)
        return [types.TextContent(type="text", text=info)]

    elif name == "list_pull_requests":
        repo = g.get_repo(f"{arguments['owner']}/{arguments['repo']}")
        prs = repo.get_pulls(state="open")
        result = "\n".join([f"PR #{pr.number}: {pr.title}" for pr in prs])
        audit.log("list_pull_requests", arguments, result)
        return [types.TextContent(type="text", text=result or "No open PRs")]

    elif name == "get_pull_request":
        repo = g.get_repo(f"{arguments['owner']}/{arguments['repo']}")
        pr = repo.get_pull(arguments["pr_number"])
        files = pr.get_files()
        diff = "\n".join([
            f"File: {f.filename}\nChanges: +{f.additions} -{f.deletions}\nPatch:\n{f.patch}"
            for f in files if f.patch
        ])
        result = f"Title: {pr.title}\nAuthor: {pr.user.login}\nDescription: {pr.body}\n\nFiles Changed:\n{diff}"
        audit.log("get_pull_request", arguments, result)
        return [types.TextContent(type="text", text=result)]

    elif name == "review_pull_request":
        # fetch the PR
        repo = g.get_repo(f"{arguments['owner']}/{arguments['repo']}")
        pr = repo.get_pull(arguments["pr_number"])
        files = pr.get_files()
        diff = "\n".join([
            f"File: {f.filename}\nPatch:\n{f.patch}"
            for f in files if f.patch
        ])

        pr_info = {
            "number": pr.number,
            "title": pr.title,
            "author": pr.user.login,
            "description": pr.body
        }

        # send to Claude with extended thinking so we capture the reasoning
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8000,
            thinking={
                "type": "enabled",
                "budget_tokens": 5000
            },
            system=REVIEW_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Review this PR:\n\nTitle: {pr.title}\nDescription: {pr.body}\n\nDiff:\n{diff}"
            }]
        )

        # extract thinking vs actual review separately
        reasoning = None
        review = None
        for block in response.content:
            if block.type == "thinking":
                reasoning = block.thinking
            elif block.type == "text":
                review = block.text

        # log everything including the reasoning
        audit.log_review(pr_info, diff, review, reasoning=reasoning)

        return [types.TextContent(type="text", text=review)]

    elif name == "get_audit_log":
        import json
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, "audit_log.json")
        entries = []
        try:
            with open(log_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if arguments.get("session_only"):
                        if entry.get("session_id") == audit.session_id:
                            entries.append(entry)
                    else:
                        entries.append(entry)
        except FileNotFoundError:
            return [types.TextContent(type="text", text="No audit log found yet")]
        
        result = json.dumps(entries, indent=2)
        return [types.TextContent(type="text", text=result)]

    elif name == "approve_review":
        audit.end_session(
            approved=arguments["approved"],
            notes=arguments["notes"]
        )
        status = "APPROVED" if arguments["approved"] else "REJECTED"
        result = f"Review {status}. Reason: {arguments['notes']}\nAudit entry closed for session {audit.session_id}"
        return [types.TextContent(type="text", text=result)]

async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())