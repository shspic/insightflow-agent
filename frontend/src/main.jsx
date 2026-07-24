import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { FeedbackProvider } from "./context/FeedbackContext";
import { ThemeProvider } from "./context/ThemeContext";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider>
      <FeedbackProvider>
        <App />
      </FeedbackProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
