import React, { useState } from 'react';
import './App.css';

function App() {
  const [files, setFiles] = useState<FileList | null>(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<string[]>([]);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) {
      setFiles(event.target.files);
    }
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.dataTransfer.files) {
      setFiles(event.dataTransfer.files);
    }
  };

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
  };

  const handleQuery = () => {
    // TODO: Implement query logic
    setResults([`Query result: ${query}`]);
  };

  const handleUpload = () => {
    // TODO: Implement file upload to S3 logic
    console.log('Upload files:', files);
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>File Query System</h1>
      </header>
      
      <main className="App-main">
        <section className="upload-section">
          <h2>File Upload</h2>
          <div 
            className="drop-zone"
            onDrop={handleDrop}
            onDragOver={handleDragOver}
          >
            <input
              type="file"
              multiple
              onChange={handleFileChange}
              style={{ display: 'none' }}
              id="file-input"
            />
            <label htmlFor="file-input" className="file-label">
              Drag and drop files here, or click to select files
            </label>
          </div>
          
          {files && (
            <div className="file-list">
              <h3>Selected Files:</h3>
              <ul>
                {Array.from(files).map((file, index) => (
                  <li key={index}>{file.name}</li>
                ))}
              </ul>
            </div>
          )}
          
          <button onClick={handleUpload} className="upload-btn">
            Upload Files
          </button>
        </section>

        <section className="query-section">
          <h2>Query</h2>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Enter query content"
            className="query-input"
          />
          <button onClick={handleQuery} className="query-btn">
            Submit Query
          </button>
        </section>

        <section className="results-section">
          <h2>Query Results</h2>
          <ul className="results-list">
            {results.map((result, index) => (
              <li key={index}>{result}</li>
            ))}
          </ul>
        </section>
      </main>
    </div>
  );
}

export default App; 