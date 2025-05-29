import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import LiveDashboard from './pages/LiveDashboard';

function App() {
  return (
    <Router>
      <div style={{ padding: '1rem' }}>
        <nav style={{ marginBottom: '1rem' }}>
          <Link to="/" style={{ marginRight: '1rem' }}>Dashboard</Link>
        </nav>

        <Routes>
          <Route path="/" element={<LiveDashboard />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
