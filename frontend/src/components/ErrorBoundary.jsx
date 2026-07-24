import { Component } from "react";
import { Link } from "react-router-dom";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="standalone-state">
          <p className="eyebrow">InsightFlow Agent</p>
          <h1>页面出现意外错误</h1>
          <p>当前页面无法继续显示，服务端任务不会因此被取消。</p>
          <Link className="ui-button ui-button--primary" to="/workspaces">返回工作区</Link>
        </main>
      );
    }
    return this.props.children;
  }
}
