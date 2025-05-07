# app.py - Flask Backend for Project Roast

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
import base64
import re
import os
import google.generativeai as genai
import random
import time
from pathlib import Path
import json

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure API keys (in production, use environment variables)
# Using an empty token to handle unauthenticated requests
# GitHub allows limited access for unauthenticated requests
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "your_github_token")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "your_gemini_api_key")

# Initialize Gemini client
genai.configure(api_key=GEMINI_API_KEY)

# Set headers based on token availability
def get_github_headers():
    if GITHUB_TOKEN:
        return {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
    else:
        return {
            "Accept": "application/vnd.github.v3+json"
        }

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")
    
@app.route('/health')
def health():
    return "Backend zinda hai bc!", 200
    
@app.route("/api/test", methods=["GET"])
def test():
    return jsonify({"status": "ok", "message": "API is working"})

@app.route("/api/roast", methods=["POST"])
def roast_project():
    try:
        print("Request received:", request.data)
        data = request.json

        if not data:
            print("No JSON data received")
            return jsonify({"error": "No JSON data received"}), 400

        repo_url = data.get("repoUrl")
        if not repo_url:
            print("No repository URL provided")
            return jsonify({"error": "No repository URL provided"}), 400

        intensity = data.get("intensity", "normal")

        valid_intensities = ["normal", "moderate", "extreme"]
        if intensity not in valid_intensities:
            intensity = "normal"

        print(f"Processing repository: {repo_url}, intensity: {intensity}")

        # Extract owner and repo name from GitHub URL
        match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
        if not match:
            return jsonify({"error": "Invalid GitHub URL"}), 400

        owner, repo = match.groups()
        print(f"Extracted owner: {owner}, repo: {repo}")

        # Fetch repository details with error handling
        try:
            repo_info = fetch_repo_info(owner, repo)
            print(f"Successfully fetched repo info for {owner}/{repo}")
        except Exception as e:
            print(f"Error fetching repo info: {str(e)}")
            # Return a more detailed error response
            return jsonify({
                "error": f"Failed to fetch repository info: {str(e)}",
                "details": "The repository might be private or doesn't exist. Please check the URL or try with a public repository."
            }), 404
            
        # Continue with the analysis
        try:
            file_structure = fetch_file_structure(owner, repo)
            code_samples = fetch_code_files(owner, repo, file_structure, max_files=10)
            analysis = analyze_project(file_structure, code_samples, repo_info)
            roast = generate_roast_from_gemini(analysis, None, intensity)
        except Exception as e:
            print(f"Error during analysis: {str(e)}")
            # Provide a fallback response with basic information
            return jsonify({
                "repoName": repo_info.get("name", "Unknown"),
                "repoOwner": owner,
                "repoStars": repo_info.get("stargazers_count", 0),
                "repoForks": repo_info.get("forks_count", 0),
                "repoDescription": repo_info.get("description", "No description"),
                "roast": f"Couldn't properly analyze this repository. Error: {str(e)}",
                "error": str(e)
            }), 200

        return jsonify({
            "repoName": repo_info.get("name", "Unknown"),
            "repoOwner": owner,
            "repoStars": repo_info.get("stargazers_count", 0),
            "repoForks": repo_info.get("forks_count", 0),
            "languages": analysis.get("languages"),
            "frameworks": analysis.get("frameworks"),
            "codeIssues": analysis.get("code_issues"),
            "stylingIssues": analysis.get("styling_issues"),
            "structureIssues": analysis.get("structure_issues"),
            "complexity": analysis.get("complexity"),
            "copiedCodeLikelihood": analysis.get("copied_code_likelihood"),
            "repoDescription": repo_info.get("description", "No description"),
            "roast": roast
        })

    except Exception as e:
        print(f"Error processing repository: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
def fetch_repo_info(owner, repo):
    """Fetch basic repository information"""
    try:
        headers = get_github_headers()
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        print(f"Fetching repo info from: {api_url}")
        
        response = requests.get(api_url, headers=headers)
        
        if response.status_code == 401:
            raise Exception(f"Unauthorized: GitHub API token is invalid or expired. Using public access mode.")
        elif response.status_code == 403:
            # Handle rate limiting
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            current_time = int(time.time())
            wait_time = max(0, reset_time - current_time)
            
            if wait_time > 0 and wait_time < 60:  # Only wait if less than a minute
                time.sleep(wait_time + 1)
                return fetch_repo_info(owner, repo)  # Try again
            else:
                raise Exception(f"Rate limited by GitHub API. Please try again later (reset in {wait_time} seconds).")
        elif response.status_code == 404:
            raise Exception(f"Repository {owner}/{repo} not found. It might be private or doesn't exist.")
            
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        # Use a fallback approach for public repositories
        try:
            # Try without authentication
            response = requests.get(f"https://api.github.com/repos/{owner}/{repo}")
            if response.status_code == 200:
                return response.json()
        except:
            pass
        
        raise Exception(f"Error fetching repo info: {e}")


def fetch_file_content(owner, repo, path):
    """Fetch and decode file content"""
    try:
        headers = get_github_headers()
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
        
        # Handle rate limiting
        if response.status_code == 403 and 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) == 0:
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            current_time = int(time.time())
            wait_time = max(0, reset_time - current_time)
            
            if wait_time > 0 and wait_time < 60:  # Only wait if less than a minute
                time.sleep(wait_time + 1)
                return fetch_file_content(owner, repo, path)  # Try again
            else:
                return f"Rate limited by GitHub API for file: {path}"
                
        response.raise_for_status()
        content = response.json().get("content", "")
        if content:
            return base64.b64decode(content).decode("utf-8")
        return ""
    except requests.exceptions.RequestException as e:
        return f"Error fetching content: {e}"
    except UnicodeDecodeError:
        return "Binary file (not analyzed)"


def fetch_file_structure(owner, repo, path=""):
    """Recursively fetch file structure"""
    try:
        headers = get_github_headers()
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        response = requests.get(api_url, headers=headers)
        
        # Handle rate limiting
        if response.status_code == 403 and 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) == 0:
            reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
            current_time = int(time.time())
            wait_time = max(0, reset_time - current_time)
            
            if wait_time > 0 and wait_time < 60:  # Only wait if less than a minute
                time.sleep(wait_time + 1)
                return fetch_file_structure(owner, repo, path)  # Try again
            else:
                print(f"Rate limited by GitHub API when fetching directory: {path}")
                return []  # Return empty list if rate limited
        
        response.raise_for_status()
        
        files = []
        for item in response.json():
            if item["type"] == "file":
                files.append(item["path"])
            elif item["type"] == "dir":
                # Skip some common directories that are likely to be large
                if item["name"] not in ["node_modules", ".git", "venv", "env", "__pycache__"]:
                    files.extend(fetch_file_structure(owner, repo, item["path"]))
        
        return files
    except requests.exceptions.RequestException as e:
        print(f"Error fetching file structure at {path}: {str(e)}")
        # For directories, better to return empty list than to fail completely
        return []


def fetch_code_files(owner, repo, file_structure, max_files=10):
    """Fetch content of important code files for analysis"""
    code_files = []
    code_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.html', '.css', '.php', '.go', '.rb']
    
    # Filter to just code files
    code_file_paths = [f for f in file_structure if any(f.endswith(ext) for ext in code_extensions)]
    
    # Safety check - if file structure is empty, use a fallback approach
    if not code_file_paths:
        print("No code files found in file structure. Using fallback approach.")
        try:
            # Try to get some common files directly
            common_files = ["app.py", "index.js", "main.py", "server.js", "index.html"]
            for file in common_files:
                content = fetch_file_content(owner, repo, file)
                if content and not content.startswith("Error"):
                    ext = os.path.splitext(file)[1]
                    code_files.append({
                        "path": file,
                        "content": content,
                        "extension": ext
                    })
                    if len(code_files) >= max_files:
                        break
        except Exception as e:
            print(f"Fallback approach also failed: {str(e)}")
    else:
        # Prioritize main files like app.py, index.js, main.py, etc.
        main_files = [f for f in code_file_paths if any(main_name in f.lower() for main_name in ['app', 'index', 'main', 'server'])]
        other_files = [f for f in code_file_paths if f not in main_files]
        
        # Fetch content from prioritized files
        prioritized_files = main_files + other_files
        for file_path in prioritized_files[:max_files]:  # Limit to max_files
            content = fetch_file_content(owner, repo, file_path)
            if content and len(content) > 0 and not content.startswith("Error"):
                code_files.append({
                    "path": file_path,
                    "content": content,
                    "extension": os.path.splitext(file_path)[1]
                })
    
    return code_files


def identify_frameworks_from_code(code_files):
    """Identify frameworks and libraries based on code content"""
    frameworks = {
        "frontend": set(),
        "backend": set(),
        "database": set(),
        "other": set()
    }
    
    framework_patterns = {
        "React": (r'import\s+.*[^a-zA-Z]React[^a-zA-Z]', "frontend"),
        "Vue": (r'import\s+.*Vue|new\s+Vue', "frontend"),
        "Angular": (r'@angular|NgModule', "frontend"),
        "Express": (r'require\s*\(\s*[\'"]express[\'"]\s*\)|import\s+.*express', "backend"),
        "Flask": (r'from\s+flask\s+import|Flask\s*\(', "backend"),
        "Django": (r'from\s+django|DJANGO_|urls\.py', "backend"),
        "FastAPI": (r'from\s+fastapi\s+import|FastAPI\s*\(', "backend"),
        "Spring": (r'@SpringBootApplication|@Controller|@RestController', "backend"),
        "Laravel": (r'use\s+Illuminate|extends\s+Model', "backend"),
        "MongoDB": (r'mongoose|MongoDB|MongoClient', "database"),
        "MySQL": (r'mysql\.|createConnection|mysqli', "database"),
        "PostgreSQL": (r'psycopg2|pg\.|pgPool', "database"),
        "SQLite": (r'sqlite3|\.db', "database"),
        "TensorFlow": (r'import\s+tensorflow|import\s+tf', "other"),
        "PyTorch": (r'import\s+torch', "other"),
        "Redux": (r'createStore|useReducer|combineReducers|useSelector', "frontend"),
        "Tailwind": (r'tailwind|className="[^"]*flex[^"]*"', "frontend"),
        "Bootstrap": (r'bootstrap\.css|class="[^"]*btn[^"]*"', "frontend"),
        "jQuery": (r'\$\(|jQuery\(', "frontend"),
        "Socket.io": (r'socket\.io|io\.on\(', "backend"),
        "GraphQL": (r'graphql|ApolloClient|gql`', "backend"),
        "Webpack": (r'webpack\.config|module\.exports', "other"),
        "Docker": (r'Dockerfile|docker-compose', "other"),
    }
    
    for file in code_files:
        for framework, (pattern, category) in framework_patterns.items():
            if re.search(pattern, file["content"], re.IGNORECASE):
                frameworks[category].add(framework)
    
    return frameworks


def identify_code_issues(code_files):
    """Identify potential code issues for roasting"""
    issues = []
    
    # Common code smells and issues to look for
    patterns = {
        "Hardcoded credentials": r'password\s*=\s*[\'"][^\'"]+[\'"]|apiKey\s*=|secret\s*=',
        "Console logging": r'console\.log\(',
        "TODO comments": r'TODO|FIXME|XXX',
        "Empty catch blocks": r'catch\s*\([^)]*\)\s*{\s*}',
        "Magic numbers": r'\b\d{4,}\b',
        "Long functions": r'function\s+\w+\s*\([^)]*\)\s*{[^}]{500,}}',
        "Global variables": r'var\s+\w+\s*=|let\s+\w+\s*=|const\s+\w+\s*=',
        "Excessive comments": r'\/\*[\s\S]{50,}\*\/|\/\/.*\n\/\/.*\n\/\/.*\n\/\/.*\n\/\/.*\n',
        "Commented code": r'\/\/\s*function|\/\/\s*for\s*\(|\/\/\s*if\s*\(',
        "Variable naming": r'\b[a-z]{1,2}\b\s*=',
    }
    
    for file in code_files:
        file_issues = {}
        for issue, pattern in patterns.items():
            matches = re.findall(pattern, file["content"], re.MULTILINE)
            if matches:
                file_issues[issue] = len(matches)
        
        if file_issues:
            issues.append({
                "file": file["path"],
                "issues": file_issues
            })
    
    return issues


def check_inconsistent_styling(code_files):
    """Check for inconsistent styling across files"""
    issues = []
    
    # Check for inconsistent indentation
    indentation_styles = {}
    for file in code_files:
        if file["extension"] in [".py", ".js", ".jsx", ".ts", ".tsx"]:
            # Check for spaces vs tabs
            spaces = len(re.findall(r'^\s+', file["content"], re.MULTILINE))
            tabs = len(re.findall(r'^\t+', file["content"], re.MULTILINE))
            
            if spaces > tabs and tabs > 0:
                issues.append(f"Mixed spaces and tabs in {file['path']}")
            
            if spaces > 0:
                indentation_styles[file["path"]] = "spaces"
            elif tabs > 0:
                indentation_styles[file["path"]] = "tabs"
    
    # Check for inconsistent quotes
    quote_styles = {}
    for file in code_files:
        if file["extension"] in [".js", ".jsx", ".ts", ".tsx"]:
            single_quotes = len(re.findall(r'\'[^\']*\'', file["content"]))
            double_quotes = len(re.findall(r'\"[^\"]*\"', file["content"]))
            
            if single_quotes > double_quotes:
                quote_styles[file["path"]] = "single"
            elif double_quotes > single_quotes:
                quote_styles[file["path"]] = "double"
    
    # Check if both styles are used across the project
    if len(set(indentation_styles.values())) > 1:
        issues.append("Inconsistent indentation (both spaces and tabs used)")
    
    if len(set(quote_styles.values())) > 1:
        issues.append("Inconsistent quotation mark style")
    
    return issues

def convert_sets_to_lists(obj):
    if isinstance(obj, dict):
        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
    elif isinstance(obj, set):
        return list(obj)
    elif isinstance(obj, list):
        return [convert_sets_to_lists(i) for i in obj]
    else:
        return obj

def analyze_project(file_structure, code_samples, repo_info):
    """Create a detailed analysis of the project for roasting"""
    # Basic repo stats
    analysis = {
        "name": repo_info.get("name", "Unknown"),
        "description": repo_info.get("description", "No description"),
        "stars": repo_info.get("stargazers_count", 0),
        "forks": repo_info.get("forks_count", 0),
        "issues": repo_info.get("open_issues_count", 0),
        "file_count": len(file_structure),
        "languages": [],
        "frameworks": {},
        "code_issues": [],
        "styling_issues": [],
        "complexity": "simple",
        "structure_issues": [],
        "copied_code_likelihood": "low",
        "code_samples": code_samples  # Store code samples for roasting
    }
    
    # Calculate language breakdown
    language_extensions = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "React/JavaScript",
        ".ts": "TypeScript",
        ".tsx": "React/TypeScript",
        ".html": "HTML",
        ".css": "CSS",
        ".java": "Java",
        ".php": "PHP",
        ".go": "Go",
        ".rb": "Ruby",
        ".c": "C",
        ".cpp": "C++",
        ".cs": "C#",
    }
    
    language_count = {}
    for file in file_structure:
        ext = os.path.splitext(file)[1].lower()
        if ext in language_extensions:
            lang = language_extensions[ext]
            language_count[lang] = language_count.get(lang, 0) + 1
    
    # Sort languages by frequency
    analysis["languages"] = sorted(language_count.items(), key=lambda x: x[1], reverse=True)
    
    # Identify frameworks from code content
    if code_samples:
        analysis["frameworks"] = identify_frameworks_from_code(code_samples)
        
        # Add code issues for roasting
        analysis["code_issues"] = identify_code_issues(code_samples)
        
        # Look for styling inconsistencies
        analysis["styling_issues"] = check_inconsistent_styling(code_samples)
        
        # Check project structure
        if ".git" not in [os.path.basename(f) for f in file_structure]:
            analysis["structure_issues"].append("No Git repository")
        
        if not any("README" in f for f in file_structure):
            analysis["structure_issues"].append("No README file")
        
        if not any("requirements.txt" in f for f in file_structure) and any(f.endswith(".py") for f in file_structure):
            analysis["structure_issues"].append("Python project without requirements.txt")
        
        if not any("package.json" in f for f in file_structure) and any(f.endswith(".js") for f in file_structure):
            analysis["structure_issues"].append("JavaScript project without package.json")
    
    # Determine project complexity
    if analysis["file_count"] < 10:
        analysis["complexity"] = "bahut simple aur bekaar" # Very simple and useless
    elif analysis["file_count"] < 30:
        analysis["complexity"] = "thoda sa complex lekin fir bhi bakwaas" # A bit complex but still nonsense
    else:
        analysis["complexity"] = "complex lekin bekar implementation ke saath" # Complex but with terrible implementation
    
    return convert_sets_to_lists(analysis)

def identify_code_anti_patterns(code_samples):
    """Identify specific anti-patterns in code for detailed roasting"""
    anti_patterns = []
    
    for file in code_samples:
        file_anti_patterns = []
        content = file["content"]
        path = file["path"]
        
        # Check for hardcoded credentials
        if re.search(r'(password|api_?key|secret|token)\s*=\s*[\'"][^\'"]{5,}[\'"]', content, re.IGNORECASE):
            file_anti_patterns.append("hardcoded credentials - full security disaster")
        
        # Check for excessive nesting
        if re.search(r'if\s*\([^)]*\)\s*{\s*if\s*\([^)]*\)\s*{\s*if', content):
            file_anti_patterns.append("triple nested if statements - code maze")
        
        # Check for commented out code blocks
        if re.search(r'(\/\/\s*function|\/\/\s*for\s*\(|\/\/\s*if\s*\(|\/\*\s*function)', content):
            file_anti_patterns.append("commented-out code blocks - lazy cleanup")
        
        # Check for very long functions
        if re.search(r'function\s+\w+\s*\([^)]*\)\s*{[^}]{500,}}', content):
            file_anti_patterns.append("functions longer than 500 characters - spaghetti code")
        
        # Check for poor variable naming
        if re.search(r'\b[a-z]{1,2}\b\s*=', content):
            file_anti_patterns.append("single letter variables - impossible to understand")
        
        # Check for repeated console logs
        console_logs = re.findall(r'console\.log', content)
        if len(console_logs) > 5:
            file_anti_patterns.append(f"{len(console_logs)} console.log statements - debugging nightmare")
        
        # Check for magic numbers
        magic_numbers = re.findall(r'[^"\'](\b\d{4,}\b)[^"\']', content)
        if len(magic_numbers) > 3:
            file_anti_patterns.append("magic numbers without constants - future maintenance hell")
        
        # Check for copy-paste code patterns
        repeated_lines = set()
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) > 30:  # Only check substantial lines
                if line in repeated_lines:
                    file_anti_patterns.append("copy-pasted code - DRY principle violation")
                    break
                repeated_lines.add(line)
        
        if file_anti_patterns:
            anti_patterns.append({
                "file": path,
                "issues": file_anti_patterns
            })
    
    return anti_patterns


def extract_core_code_snippets(repo_path, code_samples, max_files=5):
    """Extract code snippets from local repo or from already fetched code samples"""
    # If using GitHub API data (remote repos)
    if repo_path is None and code_samples:
        # Filter backend files from code samples
        backend_extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '.php']
        backend_files = [file for file in code_samples 
                         if any(file["path"].endswith(ext) for ext in backend_extensions)]
        
        # Sort by content length (as proxy for file size)
        backend_files.sort(key=lambda x: len(x["content"]), reverse=True)
        
        # Select top files
        selected = backend_files[:max_files]
        
        code_snippets = ""
        for file in selected:
            # Get up to 2000 chars of content
            content = file["content"][:2000]
            code_snippets += f"\n\n### File: {file['path']}\n{content}"
            
        return code_snippets if code_snippets else "No code files found."
    
    # If using local repo path
    elif repo_path:
        backend_extensions = ['.py', '.js', '.ts', '.jsx', '.tsx', '.php']
        backend_files = []

        for path in Path(repo_path).rglob('*'):
            if path.suffix in backend_extensions and 'node_modules' not in str(path):
                backend_files.append(path)

        backend_files.sort(key=lambda x: x.stat().st_size, reverse=True)
        selected = backend_files[:max_files]

        code_snippets = ""
        for file in selected:
            with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                code_snippets += f"\n\n### File: {file.name}\n{content[:2000]}"  # limit to ~2000 chars/file

        return code_snippets
    
    # If no repo path and no code samples
    else:
        return "No direct access to repository files."

def generate_roast_from_gemini(analysis, repo_path, intensity="normal"):
    """Generate a roast in Hinglish focusing on actual code in the files"""
    try:
        # Extract key information for the prompt
        languages = [f"{name} ({count} files)" for name, count in analysis.get("languages", [])]
        frontend_fw = list(analysis.get("frameworks", {}).get("frontend", []))
        backend_fw = list(analysis.get("frameworks", {}).get("backend", []))
        database_fw = list(analysis.get("frameworks", {}).get("database", []))
        
        # Get code samples from the analysis
        code_samples = analysis.get("code_samples", [])
        
        # Extract code snippets
        code_snippets = extract_core_code_snippets(repo_path, code_samples)
        
        # Identify specific code anti-patterns for detailed roasting
        anti_patterns = identify_code_anti_patterns(code_samples)
        
        # Format anti-patterns for the prompt
        anti_pattern_text = ""
        for ap in anti_patterns:
            file_path = ap["file"]
            issues = ap["issues"]
            anti_pattern_text += f"\nFile '{file_path}' has these issues:\n- " + "\n- ".join(issues)
        
        # Create prompt based on intensity level
        base_prompt = f"""
            Main ek GitHub project ke liye Hinglish me ek short, powerful aur mazedaar roast generate karna chahta hoon. Is baar, main chahta hoon ki roast primarily actual CODE pe focus kare - code ki quality, style, structure, aur implementation. Less focus on project concept, more focus on the actual code.

            Project ka naam: {analysis.get('name')}
            Description: {analysis.get('description')}
            Languages: {', '.join(languages) if languages else 'Kuch nahi mila'}
            Frontend frameworks: {', '.join(frontend_fw) if frontend_fw else 'Kuch nahi mila'}
            Backend frameworks: {', '.join(backend_fw) if backend_fw else 'Kuch nahi mila'}
            Database technologies: {', '.join(database_fw) if database_fw else 'Kuch nahi mila'}
            
            Code Anti-Patterns identified:
            {anti_pattern_text if anti_pattern_text else "No specific anti-patterns identified"}
        """

        # Instructions specific to each intensity level
        if intensity == "normal":
            instructions = """
                Roast ke instructions:
                1. Sirf Hinglish language ka prayog karein (Hindi + English mix with typical Hinglish slang)
                2. Short aur powerful hona chahiye (maximum 100-150 words)
                3. MOSTLY focus on the ACTUAL CODE QUALITY and IMPLEMENTATION - not just the project concept
                4. Neeche diye gaye code snippets ko analyze karein aur unke specific problems point out karein
                5. Bad coding practices, poor variable names, inefficient algorithms, security flaws pe focus karein
                6. 3-4 SPECIFIC code problems ka mention karein with file references like "app.py mein line X par..."
                7. Code style, indentation, commenting, function length, etc. pe comments karein
                8. Analogies aur metaphors ka use karein yeh batane ke liye ki code kitna bekaar hai
                9. Authentic Hinglish street slang ka istemal karein - natural lagna chahiye
                10. NO CURSE WORDS OR PROFANITY - professional criticism with humor only
                11. **Avoid karo text formatting jaise bold/italics – sirf plain output mein likhna.**

            """
        elif intensity == "moderate":
            instructions = """
                Roast ke instructions:
                1. Sirf Hinglish language ka prayog karein (Hindi + English mix with typical Hinglish slang)
                2. Short aur powerful hona chahiye (maximum 150-200 words)
                3. MOSTLY focus on the ACTUAL CODE QUALITY and IMPLEMENTATION - not just the project concept
                4. Neeche diye gaye code snippets ko analyze karein aur unke specific problems point out karein
                5. Bad coding practices, poor variable names, inefficient algorithms, security flaws pe focus karein
                6. 3-4 SPECIFIC code problems ka mention karein with file references like "app.py mein line X par..."
                7. Code style, indentation, commenting, function length, etc. pe comments karein
                8. Analogies aur metaphors ka use karein yeh batane ke liye ki code kitna bekaar hai
                9. Authentic Hinglish street slang ka istemal karein - natural lagna chahiye
                10. Mild curse words allowed - bekar, bakwas, faltu type words with 1-2 stronger words per roast
                11. Yeh roast adults ke liye hai - thoda sarcastic and harsh hona chahiye
                12. **Avoid karo text formatting jaise bold/italics – sirf plain output mein likhna.**

            """
        else:  # extreme
            instructions = """
               Roast ke instructions:

                1. Sirf Hinglish language ka use karo (Hindi + English mix, jaise gully ke dost baat karte hain).
                2. Medium length roast ho (200-250 words max), par feel aani chahiye ki bandi/banda rula diya.
                3. Focus mostly on CODE QUALITY aur IMPLEMENTATION pe karo – sirf idea ya concept pe mat atko.
                4. Neeche diye gaye code snippets ko achhe se analyze karo aur 4-5 specific code problems point out karo, file references ke sath jaise "app.py mein line 23 par..."
                5. Target karo:
                - Bad coding practices
                - Bakwas variable names
                - Inefficient logic
                - Security loopholes
                - Code structure and readability
                6. Indentation, function length, commenting, code reuse – sabko roast karo agar bura hai.
                7. Use karo solid analogies/metaphors – jaise "ye function aise behave kar raha jaise drunk uncle shaadi mein dance kar raha ho."
                8. Har paragraph mein 1-2 heavy gaaliyan zaroori hain (but avoid direct maa-behen type). Use karo short forms jaise mc, bc, bho*dike, chutiya – context ke hisaab se natural feel aaye.
                9. Roast natural lage – jaise real life gully programming review ho raha ho.
                10. **Avoid karo text formatting jaise bold/italics – sirf plain output mein likhna.**
                
        

 """

        # Add code snippets to prompt
        full_prompt = base_prompt + instructions + f"""
            Neeche diye gaye code snippets ko analyze karein aur inhi ke basis pe roast karein. 
            Specifically mention file names and problematic code patterns.
            
            Code Snippets:
            {code_snippets}
            
            Remember: Focus on the ACTUAL CODE in these snippets, not just the project concept. Give specific examples from the code.
        """

        # Set up Gemini model parameters - adjust temperature based on intensity
        temperature = 0.7 if intensity == "normal" else (0.85 if intensity == "moderate" else 1.0)
        
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={
                "temperature": temperature,
                "top_p": 0.98,
                "top_k": 50,
                "max_output_tokens": 1200,
                "candidate_count": 1,
            },
            safety_settings=[
                # Adjust safety settings based on intensity
                {"category": "HARM_CATEGORY_HARASSMENT", 
                 "threshold": "BLOCK_ONLY_HIGH" if intensity != "normal" else "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", 
                 "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", 
                 "threshold": "BLOCK_ONLY_HIGH"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", 
                 "threshold": "BLOCK_ONLY_HIGH"},
            ]
        )

        # Generate response with retries
        max_attempts = 3
        for attempt in range(max_attempts):
            response = model.generate_content(full_prompt)
            if response and hasattr(response, 'text') and len(response.text.strip()) > 100:
                return response.text

        # Fallback messages
        return generate_fallback_roast(analysis, intensity, code_samples)

    except Exception as e:
        # Generate fallback based on intensity
        return f"Roast karte waqt error aa gaya: {e}+ \n\n" + generate_fallback_roast(analysis, intensity, code_samples)



def generate_fallback_roast(analysis,intensity="normal"):
    """Generate a fallback hardcore roast in Hinglish if API fails"""
    project_name = analysis.get('name', 'Unknown Project')

    if intensity == "normal":
            return f"Lagta hai {project_name} project me itni creativity hai jitni ek blank text file me. Koi na, har kisi ko coding seekhni hai, par thoda aur practice karo."
    elif intensity == "moderate":
        return f"Yaar {project_name} project dekh ke lagta hai kisi ne Stack Overflow se copy paste karna hi coding samajh liya hai. Kitna bakwas code likha hai bhai, zara documentation likhna bhi seekh lo."
    
    elif intensity == "extreme":
        insults = [
            "Tumhara code dekhkar meri aankhen jal gayi hain",
            "Yeh code nahi, yeh to mere toilet se bhi ganda hai",
            "Tumhare code se achcha to mera 5 saal ka baccha likh dega",
            "Ise code kehte ho? Yeh to sirf bakwaas hai",
            "Tumhara project dekhkar mujhe ulti aa rahi hai",
            "Tumhara GitHub dekhkar main hans-hanskar lot-pot ho gaya",
            "Tumhare code ki architecture chaprasi ne design ki hai kya?",
            "Tum programmer nahi, keyboard par haath maarne wale bandar ho",
            "Tumhare functions ka naam dekhkar mere kaan se khoon nikal gaya",
            "Tumhara code chalta kaise hai? Chamatkar hai kya?",
            "Is project ko banane mein kitni copy-paste ki?",
            "Tumhara code dekhkar Stack Overflow bhi sharma jayega",
            "Tumhare variable name dekhkar mera sir chakra gaya"
        ]
        
        # Main language from analysis
        main_language = analysis.get("languages", [["Unknown", 0]])[0][0] if analysis.get("languages") else "Unknown"
        
        # Build a hardcore roast from templates and analysis data
        roast_parts = []
        
        # Introduction
        roast_parts.append(f"Are {analysis.get('name', 'bewakoof')}, yeh kya haga hai tune? Yeh code hai ya teri zindagi ki tarah barbaadi ka ek aur namoona?")
        
        # Language specific insults
        if "Python" in main_language:
            roast_parts.append(f"Tere {main_language} ke code ko dekhkar Python ke nirmaata Guido van Rossum khud faansi laga lenge. Itna ganda code to maine kabhi nahi dekha jo tumne {analysis.get('file_count', 0)} files mein failaya hai.")
        elif "JavaScript" in main_language or "React" in main_language:
            roast_parts.append(f"Tere {main_language} mein to koi serial killer se zyada gandagi hai. {analysis.get('file_count', 0)} files aur sabhi kachre se bhari hui hain. Tere code ki wajah se Chrome browser aatmahatya kar lega.")
        elif "Java" in main_language:
            roast_parts.append(f"Tere {main_language} code ko dekhkar meri gaand fat gayi. Itna verbose aur bakwaas code to narak mein bhi nahi milega. {analysis.get('file_count', 0)} files ka bojh aur sab kuch teri tarah bekaar.")
        else:
            roast_parts.append(f"Tere {main_language} code se to kutte ka moot bhi behtar hai. {analysis.get('file_count', 0)} files mein sirf teri bakwaas bhari hai, koi kaam ka code to hai hi nahi.")
        
        # Issues in code structure
        if analysis.get("structure_issues"):
            issues = ', '.join(analysis.get("structure_issues"))
            roast_parts.append(f"Tere project ki structure behad gandi hai - {issues}. Tu code likhne layak nahi hai, tu sirf tatti kar sakta hai jise tune code ke naam par GitHub par daal diya hai.")
        
        # Styling issues
        if analysis.get("styling_issues"):
            issues = ', '.join(analysis.get("styling_issues"))
            roast_parts.append(f"Teri coding style dekhkar mujhe ulti aa gayi - {issues}. Kya tu coding standards ke baare mein kuch jaanta bhi hai ya bas apni gaand se code nikalta hai?")
        
        # Framework choices
        frontend = list(analysis.get("frameworks", {}).get("frontend", []))
        backend = list(analysis.get("frameworks", {}).get("backend", []))
        
        if frontend:
            fw = ', '.join(frontend)
            roast_parts.append(f"Tune {fw} ka istemal kiya hai frontend ke liye? Waah! Teri bakwaas selection dekhkar to frontend developers ki aatma ro rahi hogi. Chutiya kahin ka!")
        
        if backend:
            fw = ', '.join(backend)
            roast_parts.append(f"Aur backend ke liye {fw}? Madarchod, itni bekaar technique chunne ke liye tujhe sochna pada tha ya tune random tarike se chun liya? Tera server to Hindustan ke sarkari website se bhi dheema chalega!")
        
        # Complexity
        roast_parts.append(f"Aur tere code ki complexity {analysis.get('complexity')}? Behenchod, tune itna jatil aur bekaar code kaise likha? Tu pagal hai kya? Ya fir tu sirf apne aap ko smart dikhana chahta hai, lekin tera code teri aukat dikha raha hai - ekdam ganwar ki tarah!")
        
        # Code issues
        if analysis.get("code_issues"):
            code_issues = analysis.get("code_issues")[:3]  # Take up to 3 issues
            issue_descriptions = []
            
            for issue in code_issues:
                file = issue["file"]
                problems = list(issue["issues"].keys())[:2]  # Take up to 2 problems per file
                issue_descriptions.append(f"{file} mein {', '.join(problems)}")
            
            issues_text = ', '.join(issue_descriptions)
            roast_parts.append(f"Tere code mein itni problems hain ki mujhe hansi aa rahi hai - {issues_text}. Ye tere code ki galtiyan nahi, tere janam ki galtiyan hain. Tu programmer banne ke layak nahi hai, tu sirf sadak par bheekh maangne ke layak hai.")
        
        # Stars and forks
        stars = analysis.get("stars", 0)
        forks = analysis.get("forks", 0)
        
        if stars < 5:
            roast_parts.append(f"Tere project ko matra {stars} stars mile hain? Itne to main apni gaand se nikaal dunga! Tera code itna bakwaas hai ki log ise dekhkar bhaag jaate hain.")
        
        if forks < 2:
            roast_parts.append(f"Aur sirf {forks} forks? Madarchod, tere code ko koi chhoona bhi nahi chahta! Kyunki tera code dekhne ke baad logon ka vishwas hi uth gaya hai manav jaati se!")
        
        # Production scenarios
        roast_parts.append("Agar tere is kamine code ko production mein daala gaya, to pura server aag pakad lega. Users tere ghar par patthar maarne aayenge aur tere parivar waale tujhse apna rishta tod lenge. Tu beghar ho jayega aur sadak par sote hue kutte tere muh par moot denge.")
        
        # More analogies and metaphors
        roast_parts.append("Tera code us gobar ke dher ki tarah hai jisme suar lot rahe hon. Ise chhoone se pehle 10 baar haath dhone padenge aur fir bhi gandagi nahi jayegi. Tere functions aise hain jaise kisi anpadh ganwar ne angrezi ke shabd ratte maare hon.")
        
        # Random insults from the list
        random.shuffle(insults)
        roast_parts.extend(insults[:4])  # Add 4 random insults
        
        # Conclusion
        roast_parts.append("Ant mein, tere code ki gandagi itni zyada hai ki Ganga nadi mein dubki lagakar bhi shuddh nahi hogi. Agar tu sach mein programmer banna chahta hai, to apna laptop bech de aur ja ke gaay chara. Coding tere bas ki baat nahi hai, bhosadike!")
        
        # Combine all parts
        return "\n\n".join(roast_parts)


if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
