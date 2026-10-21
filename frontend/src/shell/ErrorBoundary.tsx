import {Component, Fragment, type ErrorInfo, type ReactNode} from 'react';
import {RotateCcw} from 'lucide-react';

type Props = {name: string; children: ReactNode};
type Status = {error: Error | null; attempt: number};

// Keeps a render error in one view from blanking the rest of the app. "Reload this view" mounts the
// view again from the current state; the simulation and its connection are unaffected.
export class ErrorBoundary extends Component<Props, Status> {
  state: Status = {error: null, attempt: 0};

  static getDerivedStateFromError(error: Error): Partial<Status> {
    return {error};
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`The ${this.props.name} view failed:`, error, info.componentStack);
  }

  render() {
    const {error, attempt} = this.state;
    if (!error) return <Fragment key={attempt}>{this.props.children}</Fragment>;
    return (
      <section className="panel empty-research" role="alert">
        <h3>The {this.props.name} view stopped with an error.</h3>
        <p>{error.message || String(error)}</p>
        <p>The simulation keeps running in Python. Reload this view to show it again.</p>
        <button
          className="secondary-button"
          onClick={() => this.setState({error: null, attempt: attempt + 1})}
        >
          <RotateCcw size={13} />
          Reload this view
        </button>
      </section>
    );
  }
}
