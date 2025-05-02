from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import base64
import re
import os
import google.generativeai as genai
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
        analysis["complexity"] = "bahut simple aur bekaar"
    elif analysis["file_count"] < 30:
        analysis["complexity"] = "thoda sa complex lekin fir bhi bakwaas"
    else:
        analysis["complexity"] = "complex lekin bekar implementation ke saath"
    
    # Estimate likelihood of code copying based on patterns
    if any("COPYRIGHT" in f for f in file_structure) or any("LICENSE" in f for f in file_structure):
        analysis["copied_code_likelihood"] = "high"
    
    return analysis


def generate_roast_from_gemini(analysis):
    """Generate an extreme roast in Hinglish using Gemini API"""
    try:
        # Extract key information for the prompt
        languages = [f"{name} ({count} files)" for name, count in analysis.get("languages", [])]
        frontend_fw = list(analysis.get("frameworks", {}).get("frontend", []))
        backend_fw = list(analysis.get("frameworks", {}).get("backend", []))
        database_fw = list(analysis.get("frameworks", {}).get("database", []))
        
        # Get code samples for specific roasting
        code_issues = []
        for issue in analysis.get("code_issues", []):
            file_name = issue["file"].split("/")[-1]
            issue_list = []
            for issue_type, count in issue["issues"].items():
                issue_list.append(f"{issue_type} ({count})")
            code_issues.append(f"{file_name}: {', '.join(issue_list)}")
        
        # Create a detailed prompt for Gemini
        prompt = f"""
        मैं एक गिटहब प्रोजेक्ट के लिए हिंदी और अंग्रेजी के मिश्रण (हिंग्लिश) में एक बहुत ही कठोर और तीखा रोस्ट जेनरेट करना चाहता हूँ। यह प्रोजेक्ट बहुत बुरे कोड के साथ है और मुझे इसे बहुत आक्रामक और मजाकिया तरीके से रोस्ट करना है, लेकिन गालियों के बिना।

        प्रोजेक्ट का नाम: {analysis.get('name')}
        विवरण: {analysis.get('description')}
        स्टार्स: {analysis.get('stars')}
        फोर्क्स: {analysis.get('forks')}
        फाइल की संख्या: {analysis.get('file_count')}
        कॉम्प्लेक्सिटी: {analysis.get('complexity')}
        
        भाषाएँ: {', '.join(languages) if languages else 'कुछ नहीं मिला'}
        फ्रंटएंड फ्रेमवर्क: {', '.join(frontend_fw) if frontend_fw else 'कुछ नहीं मिला'}
        बैकएंड फ्रेमवर्क: {', '.join(backend_fw) if backend_fw else 'कुछ नहीं मिला'}
        डेटाबेस तकनीक: {', '.join(database_fw) if database_fw else 'कुछ नहीं मिला'}
        
        कोड में समस्याएँ: {', '.join(code_issues) if code_issues else 'कुछ नहीं मिला'}
        
        स्ट्रक्चर में समस्याएँ: {', '.join(analysis.get('structure_issues', []))}
        स्टाइलिंग में समस्याएँ: {', '.join(analysis.get('styling_issues', []))}
        
        रोस्ट के निर्देश:
        1. हिंग्लिश भाषा का प्रयोग करें (तीखी और आक्रामक भाषा का प्रयोग करें, पर असभ्य शब्दों का बिल्कुल प्रयोग न करें)
        2. 15-20 पंक्तियाँ होनी चाहिए
        3. अत्यंत कठोर, तीखा और आक्रामक होना चाहिए (लेकिन अभद्र भाषा के बिना)
        4. उनके कोडिंग कौशल और तकनीकी विकल्पों का मजाक उड़ाएं
        5. उनके कोड की खराब गुणवत्ता, फ्रेमवर्क में बुरे विकल्प या संरचना समस्याओं के बारे में विशिष्ट उल्लेख शामिल करें
        6. ऐसे लिखें जैसे आप उनके कोड की बुराई से बहुत नाराज हैं
        7. उनके कोड में कम से कम 3 समस्याओं का विशिष्ट उल्लेख करें
        8. उनके कोड की तुलना कचरे या बेकार चीजों से कई बार करें
        9. मजेदार परिदृश्य बनाएं कि अगर इस कोड का उपयोग प्रोडक्शन में किया जाता तो कितना बुरा होता
        10. यह बताने के लिए हिंग्लिश में रूपक और उपमाओं का उपयोग करें कि कोड कितना बुरा है
        
        बिल्कुल अभद्र शब्दों या गालियों का प्रयोग न करें, फिर भी रोस्ट उतना ही तीखा होना चाहिए। कोड की तकनीकी खामियों पर ध्यान केंद्रित करें।
        """
        
        # Set up Gemini model parameters - use high temperature for creativity
        model = genai.GenerativeModel(
            model_name="gemini-pro",
            generation_config={
                "temperature": 0.9,  # High but not maximum for better control
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 1000,
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
        
        # Generate response with retries if needed
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = model.generate_content(prompt)
                
                # Check if we got a valid response
                if response and hasattr(response, 'text') and len(response.text.strip()) > 100:
                    return response.text
                
                # If the response is too short, add a note and try again with modified prompt
                prompt += f"\n\nPlease try again with a longer, more technical roast that focuses on specific code problems."
                time.sleep(1)  # Short pause between attempts
            except Exception as inner_e:
                print(f"Attempt {attempt+1} failed: {inner_e}")
                time.sleep(2)  # Slightly longer pause after an error
        
        # If all attempts fail, return a simple message
        return "Unable to generate a roast at this time. Please try again later."
            
    except Exception as e:
        # Log the error and return a simple message
        print(f"Error with Gemini API: {e}")
        return "Unable to generate a roast at this time. Please try again later."


if __name__ == "__main__":
    # Get port from environment variable or use default
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)