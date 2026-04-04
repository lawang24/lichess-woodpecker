import { Routes, Route } from 'react-router-dom'
import Home from './pages/Home.jsx'
import SetDetail from './pages/SetDetail.jsx'

export default function App() {
  return (
    <>
      <div className="header">
        <div>
          <h1>Chess Woodpecker</h1>
          <h2>Tactical pattern training</h2>
        </div>
      </div>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/sets/:setId" element={<SetDetail />} />
      </Routes>
    </>
  )
}
