# app.py - Flask Backend for Project Roast

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import base64
import re
import os
import google.generativeai as genai
import random
import time

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure API keys (in production, use environment variables)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "your_github_token")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "your_gemini_api_key")

# Initialize Gemini client
genai.configure(api_key=GEMINI_API_KEY)

# Headers for GitHub API
headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

@app.route("/api/roast", methods=["POST"])
def roast_project():
    data = request.json
    repo_url = data.get("repoUrl")
    
    if not repo_url:
        return jsonify({"error": "No repository URL provided"}), 400
    
    try:
        # Extract owner and repo name from GitHub URL
        match = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
        if not match:
            return jsonify({"error": "Invalid GitHub URL"}), 400
        
        owner, repo = match.groups()
        
        # Fetch repository details
        repo_info = fetch_repo_info(owner, repo)
        file_structure = fetch_file_structure(owner, repo)
        
        # Fetch and analyze actual code files (up to 10 main files)
        code_samples = fetch_code_files(owner, repo, file_structure, max_files=10)
        
        # Analyze the project based on files and code
        analysis = analyze_project(file_structure, code_samples, repo_info)
        
        # Generate a hardcore roast based on the detailed analysis
        roast = generate_roast_from_gemini(analysis)
        
        return jsonify({
            "repoName": repo_info.get("name", "Unknown"),
            "repoOwner": owner,
            "repoStars": repo_info.get("stargazers_count", 0),
            "repoForks": repo_info.get("forks_count", 0),
            "languages": analysis.get("languages"),
            "roast": roast
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def fetch_repo_info(owner, repo):
    """Fetch basic repository information"""
    try:
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error fetching repo info: {e}")


def fetch_file_content(owner, repo, path):
    """Fetch and decode file content"""
    try:
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
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
        response = requests.get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}", headers=headers)
        response.raise_for_status()
        
        files = []
        for item in response.json():
            if item["type"] == "file":
                files.append(item["path"])
            elif item["type"] == "dir":
                files.extend(fetch_file_structure(owner, repo, item["path"]))  # Recursively fetch files inside directories
        
        return files
    except requests.exceptions.RequestException as e:
        raise Exception(f"Error fetching file structure: {e}")


def fetch_code_files(owner, repo, file_structure, max_files=10):
    """Fetch content of important code files for analysis"""
    code_files = []
    code_extensions = ['.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.html', '.css', '.php', '.go', '.rb']
    
    # Filter to just code files
    code_file_paths = [f for f in file_structure if any(f.endswith(ext) for ext in code_extensions)]
    
    # Prioritize main files like app.py, index.js, main.py, etc.
    main_files = [f for f in code_file_paths if any(main_name in f.lower() for main_name in ['app', 'index', 'main', 'server'])]
    other_files = [f for f in code_file_paths if f not in main_files]
    
    # Fetch content from prioritized files
    prioritized_files = main_files + other_files
    for file_path in prioritized_files[:max_files]:  # Limit to max_files
        content = fetch_file_content(owner, repo, file_path)
        if content and len(content) > 0:
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
        "copied_code_likelihood": "low"
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
    
    # Estimate likelihood of code copying based on patterns
    if any("COPYRIGHT" in f for f in file_structure) or any("LICENSE" in f for f in file_structure):
        analysis["copied_code_likelihood"] = "high"
    
    return analysis


def generate_roast_from_gemini(analysis):
    """Generate a roast in Hinglish using Gemini API with proper error handling"""
    try:
        # Extract key information for the prompt
        languages = [f"{name} ({count} files)" for name, count in analysis.get("languages", [])]
        frontend_fw = list(analysis.get("frameworks", {}).get("frontend", []))
        backend_fw = list(analysis.get("frameworks", {}).get("backend", []))
        database_fw = list(analysis.get("frameworks", {}).get("database", []))
        
        # Get code issues for specific roasting
        code_issues = []
        for issue in analysis.get("code_issues", []):
            file_name = issue["file"].split("/")[-1]
            issue_list = []
            for issue_type, count in issue["issues"].items():
                issue_list.append(f"{issue_type} ({count})")
            code_issues.append(f"{file_name}: {', '.join(issue_list)}")
        
        # Detailed information about structure issues
        structure_issues = analysis.get("structure_issues", [])
        styling_issues = analysis.get("styling_issues", [])
        
        # Create a cleaner prompt for Gemini that won't trigger content filters
        prompt = f"""
        I need to generate a humorous roast in Hinglish for a GitHub project. The roast should focus on the project's concept, features, and implementation issues.

        Project details:
        - Name: {analysis.get('name')}
        - Description: {analysis.get('description')}
        - Stars: {analysis.get('stars')}
        - Forks: {analysis.get('forks')}
        - File count: {analysis.get('file_count')}
        
        Technical details:
        - Languages: {', '.join(languages) if languages else 'None found'}
        - Frontend frameworks: {', '.join(frontend_fw) if frontend_fw else 'None found'}
        - Backend frameworks: {', '.join(backend_fw) if backend_fw else 'None found'}
        - Database technologies: {', '.join(database_fw) if database_fw else 'None found'}
        - Structure issues: {', '.join(structure_issues) if structure_issues else 'None found'}
        - Styling issues: {', '.join(styling_issues) if styling_issues else 'None found'}
        - Code complexity: {analysis.get('complexity')}
        
        Code issues found:
        {chr(10).join(code_issues) if code_issues else 'No specific issues found'}
        
        Instructions:
        1. Write a 150-200 word critique in Hinglish (mix of Hindi and English)
        2. Use a humorous, sarcastic tone like a frustrated senior developer
        3. Focus on actual project features and their implementation
        4. Question the choices made in technology, structure, and code quality
        5. Incorporate colorful expressions but keep it professional enough
        6. End with an exasperated conclusion about the project
        
        Note: Focus on actual project purpose and implementation rather than generic comments. If it's a tool, explain why this tool might be ineffective; if it's a social app, explain why users might not use it.
        """
        
        # Set up Gemini model parameters with more conservative settings
        model = genai.GenerativeModel(
            model_name="gemini-pro",
            generation_config={
                "temperature": 0.85,  # Slightly lower for more controlled output
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 800,
                "candidate_count": 1,
            },
            safety_settings=[
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_MEDIUM_AND_ABOVE",
                },
            ]
        )
        
        # Generate response with better error handling
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = model.generate_content(prompt)
                
                # Check if we got a valid response
                if response and hasattr(response, 'text') and len(response.text.strip()) > 50:
                    print(f"Successfully generated roast on attempt {attempt+1}")
                    return response.text
                else:
                    print(f"Attempt {attempt+1} returned invalid or empty response")
                    
                # If we get here, the response was too short - modify prompt slightly
                if attempt < max_attempts - 1:
                    prompt += f"\n\nPlease provide a more detailed critique. Be creative but professional."
                    time.sleep(1)  # Short pause between attempts
                    
            except Exception as inner_e:
                print(f"Attempt {attempt+1} failed with error: {str(inner_e)}")
                if "safety" in str(inner_e).lower():
                    # If safety filter triggered, make prompt more conservative
                    prompt = prompt.replace("humorous, sarcastic", "thoughtful, constructive")
                    prompt = prompt.replace("colorful expressions", "clear explanations")
                time.sleep(2)  # Slightly longer pause after an error
        
        # If all attempts fail, use fallback with explanation
        print("All Gemini API attempts failed, using fallback")
        return generate_fallback_roast(analysis, error_reason="API response issues")
            
    except Exception as e:
        # Log the detailed error and use fallback
        print(f"Error with Gemini API: {str(e)}")
        return generate_fallback_roast(analysis, error_reason=str(e))


def generate_fallback_roast(analysis, error_reason="unknown error"):
    """Generate a fallback roast in Hinglish with improved variety"""
    # Log the reason for fallback for debugging
    print(f"Using fallback roast due to: {error_reason}")
    
    # More varied templates with project-specific details included
    project_name = analysis.get('name', 'Unknown Project')
    file_count = analysis.get('file_count', 0)
    languages = [lang[0] for lang in analysis.get("languages", [])] if analysis.get("languages") else ["Unknown"]
    main_language = languages[0] if languages else "Unknown"
    
    # Framework mentions
    frontend = list(analysis.get("frameworks", {}).get("frontend", []))
    backend = list(analysis.get("frameworks", {}).get("backend", []))
    
    templates = [
        f"Arrey bhai, ye '{project_name}' kya bana diya tune? {file_count} files mein sirf confusion hi confusion hai! {main_language} ka use karke bhi kuch dhang ka nahi bana paya.",
        
        f"Oh hello developer sahab! Aapka ye '{project_name}' project dekhkar meri ankhen taras gayi. Itna {main_language} code likhne ke baad bhi kuch khaas nahi bana? Waah!",
        
        f"Bhai {project_name} ko dekh ke dil ro raha hai. {file_count} files banake bhi koi functionality nahi? {main_language} ko aapne sharminda kar diya hai!",
        
        f"Tumhara {project_name} project dekhkar mujhe vishwas ho gaya ki coding sikhi nahi jati, yeh janmjaat hoti hai. Aur tumhare case mein, yeh bilkul bhi nahi hui!",
        
        f"{project_name} ke source code ko dekhkar samajh gaya ki tumne {main_language} kyun sikha - kyunki isme copy-paste aasaan hai! Stack Overflow zindabad!",
    ]
    
    # Randomly select a template
    import random
    intro = random.choice(templates)
    
    # Add project specific elements based on analysis
    project_specifics = []
    
    # Language criticism
    if "Python" in main_language:
        project_specifics.append(f"Python itni simple language hai, fir bhi tumne usko kitna complicated bana diya! Indentation mein bhi consistency nahi hai.")
    elif "JavaScript" in main_language:
        project_specifics.append(f"JavaScript mein itne frameworks hote hue bhi tumne {', '.join(frontend) if frontend else 'kuch dhang ka'} nahi chunna. Callback hell se nikalne ki koshish bhi nahi ki!")
    elif "Java" in main_language:
        project_specifics.append("Java ka matlab hai verbosity, lekin tumne to had hi kar di! Itne classes, itne interfaces, aur functionality kuch bhi nahi.")
    
    # Structure issues
    if analysis.get("structure_issues"):
        issues = analysis.get("structure_issues")
        sample_issue = random.choice(issues) if issues else "basic structure"
        project_specifics.append(f"Project structure mein '{sample_issue}' issue hai. Kya tumne structure ke baare mein kabhi suna hai?")
    
    # Code issues
    if analysis.get("code_issues"):
        code_issues = analysis.get("code_issues")
        if code_issues:
            sample_file = code_issues[0]["file"].split("/")[-1]
            sample_issues = list(code_issues[0]["issues"].keys())
            if sample_issues:
                project_specifics.append(f"'{sample_file}' mein '{sample_issues[0]}' type ke issues hain. Coding standards naam ki koi cheez hoti hai!")
    
    # Frameworks
    if frontend or backend:
        fw_list = frontend + backend
        if fw_list:
            frameworks = ", ".join(fw_list[:2])
            project_specifics.append(f"Tumne {frameworks} ka use kiya hai lekin implementation bilkul bakwas hai. Documentation padha bhi tha ya sirf naam sunke code likha?")
    
    # Stars and forks comment
    stars = analysis.get("stars", 0)
    forks = analysis.get("forks", 0)
    project_specifics.append(f"Sirf {stars} stars aur {forks} forks? Kya baat hai! Tumhare project ko ignore karne mein duniya expert hai.")
    
    # Add conclusion
    conclusions = [
        f"Meri salah hai, ya to coding chhod do ya phir {project_name} ko private repository mein chhupa do. Public mein rakhoge to log hansenge!",
        
        f"Tumhare project ko dekhkar mujhe yaad aya ki intern ko kaam kyun nahi dena chahiye. {project_name} ko rewrite karne mein kam se kam 6 mahine lagenge!",
        
        f"Agar {project_name} production mein gaya to users tumhare ghar pe aake protest karenge. Abhi bhi time hai, delete kar do ise GitHub se!",
        
        f"Overall, {project_name} ek masterclass hai - how NOT to write code. Ise computer science universities mein 'Bad Examples' section mein rakhna chahiye.",
    ]
    
    conclusion = random.choice(conclusions)
    
    # Combine all parts
    all_parts = [intro] + random.sample(project_specifics, min(3, len(project_specifics))) + [conclusion]
    return "\n\n".join(all_parts)

if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)