import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./react.css";
class ErrorBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    return this.state.error ? (
      <div className="react-fatal" role="alert">
        <h1>Не удалось открыть интерфейс</h1>
        <p>{this.state.error.message}</p>
        <button className="button primary" onClick={() => location.reload()}>
          Перезагрузить
        </button>
      </div>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
