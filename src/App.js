// App.js - React Frontend for Project Roast

import React, { useState } from 'react';
import './App.css';
import { FaGithub, FaCode, FaStar, FaCodeBranch, FaSpinner } from 'react-icons/fa';

function App() {
  const [repoUrl, setRepoUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [roastResult, setRoastResult] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Basic validation
    if (!repoUrl.includes('github.com')) {
      setError('Please enter a valid GitHub repository URL');
      return;
    }
    
    setIsLoading(true);
    setError('');
    setRoastResult(null);
    
    try {
      const response = await fetch('https://project-roast.onrender.com/api/roast', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ repoUrl }),
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to roast the project');
      }
      
      const data = await response.json();
      setRoastResult(data);
    } catch (err) {
      setError(err.message || 'An error occurred while roasting the project');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="logo-container">
          <FaCode className="logo-icon" />
          <h1>Project Roast</h1>
        </div>
        <p className="tagline">Get your GitHub project roasted in Hinglish!</p>
      </header>
      
      <main className="content">
        <form className="repo-form" onSubmit={handleSubmit}>
          <div className="input-container">
            <FaGithub className="input-icon" />
            <input
              type="text"
              placeholder="Paste GitHub repository URL (e.g., https://github.com/username/repo)"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              className="repo-input"
              disabled={isLoading}
            />
          </div>
          
          <button 
            type="submit" 
            className="roast-button"
            disabled={isLoading || !repoUrl}
          >
            {isLoading ? <FaSpinner className="spinner" /> : 'Roast This Project!'}
          </button>
        </form>
        
        {error && (
          <div className="error-message">
            <p>{error}</p>
          </div>
        )}
        
        {roastResult && (
          <div className="result-container">
            <div className="repo-info">
              <h2>{roastResult.repoName}</h2>
              <p className="repo-description">{roastResult.repoDescription || 'No description available'}</p>
              
              <div className="repo-stats">
                <div className="stat">
                  <FaStar />
                  <span>{roastResult.repoStars} stars</span>
                </div>
                <div className="stat">
                  <FaCodeBranch />
                  <span>{roastResult.repoForks} forks</span>
                </div>
              </div>
              
              <div className="languages">
                {Object.entries(roastResult.languages).map(([lang, bytes]) => (
                  <span key={lang} className="language-tag">
                    {lang}
                  </span>
                ))}
              </div>
            </div>
            
            <div className="roast-container">
              <h3>The Roast 🔥</h3>
              <div className="roast-content">
                <p>{roastResult.roast}</p>
              </div>
            </div>
          </div>
        )}
      </main>
      
      <footer className="app-footer">
        <p>Created with ❤️ by a developer who loves code roasting</p>
      </footer>
    </div>
  );
}

export default App;