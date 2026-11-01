import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './auth';
import { NoticeProvider } from './notice';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <NoticeProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </NoticeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
