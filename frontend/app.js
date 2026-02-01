const { useState, useEffect, useRef, useCallback, createContext, useContext } = React;

// API Configuration
const API_BASE = 'http://localhost:8000';
const WS_URL = 'ws://localhost:8000/ws/track';

// Theme Context
const ThemeContext = createContext();

function ThemeProvider({ children }) {
    const [theme, setTheme] = useState(() => {
        return localStorage.getItem('theme') || 'bloomberg';
    });

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
    }, [theme]);

    return (
        <ThemeContext.Provider value={{ theme, setTheme }}>
            {children}
        </ThemeContext.Provider>
    );
}

function useTheme() {
    return useContext(ThemeContext);
}

// Chart colors by theme
const chartColors = {
    bloomberg: {
        premium: '#00ff00',
        stock: '#ffb000',
        spread: '#ff3333',
        grid: '#222222',
        bg: '#111111',
        text: '#ffffff',
        hoverlabel: { bgcolor: '#111111', font: { color: '#ffffff' } }
    },
    fintech: {
        premium: '#10b981',
        stock: '#06b6d4',
        spread: '#ef4444',
        grid: '#2a2a38',
        bg: '#1c1c26',
        text: '#ffffff',
        hoverlabel: { bgcolor: '#1c1c26', font: { color: '#ffffff' } }
    },
    retro: {
        premium: '#ffd700',
        stock: '#39ff14',
        spread: '#ff3366',
        grid: '#1a1a40',
        bg: '#12122e',
        text: '#ffd700',
        hoverlabel: { bgcolor: '#12122e', font: { color: '#ffd700' } }
    },
    swiss: {
        premium: '#ff0000',
        stock: '#000000',
        spread: '#888888',
        grid: '#dddddd',
        bg: '#ffffff',
        text: '#000000',
        hoverlabel: { bgcolor: '#ffffff', font: { color: '#000000' } }
    }
};

// Header Component
function Header({ connectionStatus, isTracking }) {
    const { theme, setTheme } = useTheme();
    const themes = ['bloomberg', 'fintech', 'retro', 'swiss'];

    const getStatusClass = () => {
        if (isTracking) return 'tracking';
        if (connectionStatus === 'connected') return 'connected';
        return '';
    };

    const getStatusText = () => {
        if (isTracking) return 'Tracking';
        if (connectionStatus === 'connected') return 'Connected';
        if (connectionStatus === 'connecting') return 'Connecting...';
        return 'Disconnected';
    };

    return (
        <header className="header">
            <div className="logo">
                <svg className="logo-icon" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M3 13h1v7c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-7h1a1 1 0 0 0 .4-1.92l-9-4a1 1 0 0 0-.8 0l-9 4A1 1 0 0 0 3 13zm7 6v-4h4v4h-4zm6-4h2v4h-2v-4zM6 15h2v4H6v-4z"/>
                    <path d="M12 2L2 7l10 4.5L22 7 12 2z"/>
                </svg>
                Options Premium Tracker
            </div>
            <div className="header-controls">
                <div className="connection-status">
                    <span className={`status-dot ${getStatusClass()}`}></span>
                    {getStatusText()}
                </div>
                <div className="theme-switcher">
                    {themes.map(t => {
                        const names = {
                            bloomberg: 'Bloomberg',
                            fintech: 'Fintech',
                            retro: 'Retro',
                            swiss: 'Swiss'
                        };
                        return (
                            <button
                                key={t}
                                className={`theme-btn ${theme === t ? 'active' : ''}`}
                                data-theme={t}
                                data-tooltip={names[t]}
                                onClick={() => setTheme(t)}
                            />
                        );
                    })}
                </div>
            </div>
        </header>
    );
}

// Sidebar Component
function Sidebar({ onStartTracking, onStopTracking, isTracking, isLoading }) {
    const [ticker, setTicker] = useState('AAPL');
    const [putCall, setPutCall] = useState('call');
    const [strikes, setStrikes] = useState([]);
    const [selectedStrike, setSelectedStrike] = useState(null);
    const [contracts, setContracts] = useState([]);
    const [selectedContract, setSelectedContract] = useState(null);
    const [stockPrice, setStockPrice] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    const loadStrikes = async () => {
        setLoading(true);
        setError(null);
        setStrikes([]);
        setContracts([]);
        setSelectedStrike(null);
        setSelectedContract(null);

        try {
            const res = await fetch(`${API_BASE}/api/strikes/${ticker.toUpperCase()}/${putCall}`);
            if (!res.ok) throw new Error('Failed to load strikes');
            const data = await res.json();
            setStrikes(data.strikes);
            setStockPrice(data.stock_price);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const loadContracts = async () => {
        if (!selectedStrike) return;
        setLoading(true);
        setError(null);
        setContracts([]);
        setSelectedContract(null);

        try {
            const res = await fetch(`${API_BASE}/api/contracts/${ticker.toUpperCase()}/${selectedStrike}/${putCall}`);
            if (!res.ok) throw new Error('Failed to load contracts');
            const data = await res.json();
            setContracts(data.contracts);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleStart = () => {
        if (!selectedContract) return;
        onStartTracking({
            ticker: ticker.toUpperCase(),
            contract: selectedContract.ticker,
            expiration: selectedContract.expiration,
            strike: selectedStrike,
            put_call: putCall,
            dte: selectedContract.dte
        });
    };

    const handleClear = () => {
        onStopTracking();
        setStrikes([]);
        setContracts([]);
        setSelectedStrike(null);
        setSelectedContract(null);
        setStockPrice(null);
    };

    return (
        <aside className="sidebar">
            <div className="sidebar-section">
                <div className="sidebar-title">Configuration</div>

                <div className="form-group">
                    <label className="form-label">Ticker Symbol</label>
                    <input
                        type="text"
                        className="form-input"
                        value={ticker}
                        onChange={e => setTicker(e.target.value.toUpperCase())}
                        placeholder="AAPL"
                        disabled={isTracking}
                    />
                </div>

                <div className="form-group">
                    <label className="form-label">Option Type</label>
                    <select
                        className="form-select"
                        value={putCall}
                        onChange={e => setPutCall(e.target.value)}
                        disabled={isTracking}
                    >
                        <option value="call">Call</option>
                        <option value="put">Put</option>
                    </select>
                </div>

                <button
                    className="btn btn-secondary btn-block"
                    onClick={loadStrikes}
                    disabled={loading || isTracking || !ticker}
                >
                    {loading ? <span className="spinner"></span> : 'Load Strikes'}
                </button>
            </div>

            {stockPrice && (
                <div className="sidebar-section">
                    <div className="metric">
                        <div className="metric-label">{ticker} Price</div>
                        <div className="metric-value">${stockPrice.toFixed(2)}</div>
                    </div>
                </div>
            )}

            {strikes.length > 0 && (
                <div className="sidebar-section">
                    <div className="divider"></div>

                    <div className="form-group">
                        <label className="form-label">Strike Price</label>
                        <select
                            className="form-select"
                            value={selectedStrike || ''}
                            onChange={e => setSelectedStrike(parseFloat(e.target.value))}
                            disabled={isTracking}
                        >
                            <option value="">Select strike...</option>
                            {strikes.map(s => (
                                <option key={s} value={s}>${s.toFixed(2)}</option>
                            ))}
                        </select>
                    </div>

                    <button
                        className="btn btn-secondary btn-block"
                        onClick={loadContracts}
                        disabled={loading || isTracking || !selectedStrike}
                    >
                        {loading ? <span className="spinner"></span> : 'Load Expirations'}
                    </button>
                </div>
            )}

            {contracts.length > 0 && (
                <div className="sidebar-section">
                    <div className="divider"></div>

                    <div className="form-group">
                        <label className="form-label">Expiration Date</label>
                        <select
                            className="form-select"
                            value={selectedContract ? selectedContract.ticker : ''}
                            onChange={e => {
                                const c = contracts.find(c => c.ticker === e.target.value);
                                setSelectedContract(c);
                            }}
                            disabled={isTracking}
                        >
                            <option value="">Select expiration...</option>
                            {contracts.map(c => (
                                <option key={c.ticker} value={c.ticker}>
                                    {c.expiration} ({c.dte} DTE)
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="divider"></div>

                    <div className="btn-group">
                        <button
                            className="btn btn-primary"
                            onClick={handleStart}
                            disabled={isTracking || !selectedContract}
                        >
                            Start
                        </button>
                        <button
                            className="btn btn-danger"
                            onClick={onStopTracking}
                            disabled={!isTracking}
                        >
                            Stop
                        </button>
                    </div>
                </div>
            )}

            {error && (
                <div className="sidebar-section">
                    <div style={{ color: 'var(--accent-danger)', fontSize: '0.75rem' }}>
                        {error}
                    </div>
                </div>
            )}

            <div className="sidebar-section">
                <div className="divider"></div>
                <button className="btn btn-secondary btn-block" onClick={handleClear}>
                    Clear Data
                </button>
            </div>
        </aside>
    );
}

// Contract Info Component
function ContractInfo({ config }) {
    if (!config) return null;

    return (
        <div className="contract-info">
            <div className="contract-info-item">
                <div className="contract-info-label">Underlying</div>
                <div className="contract-info-value">{config.ticker}</div>
            </div>
            <div className="contract-info-item">
                <div className="contract-info-label">Strike</div>
                <div className="contract-info-value">${config.strike.toFixed(2)}</div>
            </div>
            <div className="contract-info-item">
                <div className="contract-info-label">Type</div>
                <div className="contract-info-value">{config.put_call.toUpperCase()}</div>
            </div>
            <div className="contract-info-item">
                <div className="contract-info-label">Expiration</div>
                <div className="contract-info-value">{config.expiration}</div>
            </div>
            <div className="contract-info-item">
                <div className="contract-info-label">DTE</div>
                <div className="contract-info-value">{config.dte}</div>
            </div>
        </div>
    );
}

// Metrics Bar Component
function MetricsBar({ data }) {
    if (data.length === 0) return null;

    const latest = data[data.length - 1];
    const prev = data.length > 1 ? data[data.length - 2] : null;

    const getDelta = (current, previous, key) => {
        if (!previous) return null;
        return current[key] - previous[key];
    };

    const formatDelta = (delta, prefix = '$', suffix = '') => {
        if (delta === null) return null;
        const sign = delta >= 0 ? '+' : '';
        return `${sign}${prefix}${delta.toFixed(2)}${suffix}`;
    };

    const premiumDelta = getDelta(latest, prev, 'premium');
    const stockDelta = getDelta(latest, prev, 'stock_price');
    const spreadDelta = getDelta(latest, prev, 'spread_pct');

    return (
        <div className="metrics-bar">
            <div className="metric">
                <div className="metric-label">Option Premium (Mid)</div>
                <div className="metric-value">${latest.premium.toFixed(2)}</div>
                {premiumDelta !== null && (
                    <div className={`metric-delta ${premiumDelta >= 0 ? 'positive' : 'negative'}`}>
                        {formatDelta(premiumDelta)}
                    </div>
                )}
            </div>
            <div className="metric">
                <div className="metric-label">Stock Price</div>
                <div className="metric-value">${latest.stock_price.toFixed(2)}</div>
                {stockDelta !== null && (
                    <div className={`metric-delta ${stockDelta >= 0 ? 'positive' : 'negative'}`}>
                        {formatDelta(stockDelta)}
                    </div>
                )}
            </div>
            <div className="metric">
                <div className="metric-label">Spread %</div>
                <div className="metric-value">{latest.spread_pct.toFixed(2)}%</div>
                {spreadDelta !== null && (
                    <div className={`metric-delta ${spreadDelta >= 0 ? 'positive' : 'negative'}`}>
                        {formatDelta(spreadDelta, '', '%')}
                    </div>
                )}
            </div>
        </div>
    );
}

// Greeks Bar Component
function GreeksBar({ data }) {
    if (data.length === 0) return null;

    const latest = data[data.length - 1];
    const od = latest.option_data;

    const formatValue = (val, prefix = '', suffix = '', decimals = 2) => {
        if (val === null || val === undefined) return 'N/A';
        return `${prefix}${Number(val).toFixed(decimals)}${suffix}`;
    };

    const formatInt = (val) => {
        if (val === null || val === undefined) return 'N/A';
        return Number(val).toLocaleString();
    };

    return (
        <div className="greeks-bar">
            <div className="greek">
                <div className="greek-label">Bid</div>
                <div className="greek-value">{formatValue(od.bid, '$')}</div>
            </div>
            <div className="greek">
                <div className="greek-label">Ask</div>
                <div className="greek-value">{formatValue(od.ask, '$')}</div>
            </div>
            <div className="greek">
                <div className="greek-label">Last</div>
                <div className="greek-value">{formatValue(od.last, '$')}</div>
            </div>
            <div className="greek">
                <div className="greek-label">IV</div>
                <div className="greek-value">{od.iv ? formatValue(od.iv * 100, '', '%', 1) : 'N/A'}</div>
            </div>
            <div className="greek">
                <div className="greek-label">Volume</div>
                <div className="greek-value">{formatInt(od.volume)}</div>
            </div>
            <div className="greek">
                <div className="greek-label">Open Int</div>
                <div className="greek-value">{formatInt(od.open_interest)}</div>
            </div>
        </div>
    );
}

// Chart Component
function Chart({ data }) {
    const chartRef = useRef(null);
    const { theme } = useTheme();
    const colors = chartColors[theme];

    useEffect(() => {
        if (!chartRef.current || data.length === 0) return;

        const timestamps = data.map(d => new Date(d.timestamp));
        const premiums = data.map(d => d.premium);
        const stockPrices = data.map(d => d.stock_price);
        const spreads = data.map(d => d.spread_pct);

        const traces = [
            {
                x: timestamps,
                y: premiums,
                name: 'Option Premium',
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: colors.premium, width: 2 },
                marker: { size: 6 },
                yaxis: 'y'
            },
            {
                x: timestamps,
                y: stockPrices,
                name: 'Stock Price',
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: colors.stock, width: 2 },
                marker: { size: 6 },
                yaxis: 'y2'
            },
            {
                x: timestamps,
                y: spreads,
                name: 'Spread %',
                type: 'scatter',
                mode: 'lines+markers',
                fill: 'tozeroy',
                line: { color: colors.spread, width: 2 },
                marker: { size: 6 },
                fillcolor: colors.spread + '33',
                xaxis: 'x2',
                yaxis: 'y3'
            }
        ];

        const layout = {
            grid: {
                rows: 2,
                columns: 1,
                pattern: 'independent',
                roworder: 'top to bottom'
            },
            xaxis: {
                domain: [0, 1],
                showgrid: true,
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 10 },
                showticklabels: false
            },
            xaxis2: {
                domain: [0, 1],
                anchor: 'y3',
                showgrid: true,
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 10 }
            },
            yaxis: {
                domain: [0.35, 1],
                title: { text: 'Premium ($)', font: { color: colors.text, size: 11 } },
                showgrid: true,
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 10 },
                side: 'left'
            },
            yaxis2: {
                domain: [0.35, 1],
                title: { text: 'Stock Price ($)', font: { color: colors.text, size: 11 } },
                showgrid: false,
                tickfont: { color: colors.text, size: 10 },
                side: 'right',
                overlaying: 'y'
            },
            yaxis3: {
                domain: [0, 0.25],
                title: { text: 'Spread %', font: { color: colors.text, size: 11 } },
                showgrid: true,
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 10 },
                anchor: 'x2'
            },
            paper_bgcolor: 'transparent',
            plot_bgcolor: colors.bg,
            font: { color: colors.text },
            hoverlabel: colors.hoverlabel,
            legend: {
                orientation: 'h',
                y: 1.12,
                x: 0.5,
                xanchor: 'center',
                font: { size: 11 }
            },
            margin: { l: 60, r: 60, t: 30, b: 40 },
            hovermode: 'x unified'
        };

        const config = {
            responsive: true,
            displayModeBar: false
        };

        Plotly.react(chartRef.current, traces, layout, config);
    }, [data, theme]);

    if (data.length === 0) return null;

    return (
        <div className="chart-container">
            <div className="chart-title">Premium & Stock Price</div>
            <div ref={chartRef} style={{ width: '100%', height: '500px' }}></div>
        </div>
    );
}

// Data Table Component
function DataTable({ data }) {
    const [isOpen, setIsOpen] = useState(false);

    if (data.length === 0) return null;

    const displayData = [...data].reverse().slice(0, 20);

    return (
        <div className="data-table-container">
            <div className="data-table-header" onClick={() => setIsOpen(!isOpen)}>
                <span className="data-table-title">Raw Data</span>
                <span className={`data-table-toggle ${isOpen ? 'open' : ''}`}>
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                        <path d="M2 4l4 4 4-4z"/>
                    </svg>
                </span>
            </div>
            {isOpen && (
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Premium ($)</th>
                            <th>Stock ($)</th>
                            <th>Spread (%)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {displayData.map((d, i) => (
                            <tr key={i}>
                                <td>{new Date(d.timestamp).toLocaleTimeString()}</td>
                                <td>{d.premium.toFixed(2)}</td>
                                <td>{d.stock_price.toFixed(2)}</td>
                                <td>{d.spread_pct.toFixed(2)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    );
}

// Empty State Component
function EmptyState() {
    return (
        <div className="empty-state">
            <div className="empty-state-icon">📈</div>
            <div className="empty-state-text">
                Configure your options parameters in the sidebar and click 'Start' to begin tracking.
            </div>
        </div>
    );
}

// Main Content Component
function MainContent({ data, config, isTracking }) {
    if (!config) {
        return (
            <main className="main">
                <EmptyState />
            </main>
        );
    }

    return (
        <main className="main">
            <ContractInfo config={config} />
            {data.length === 0 && isTracking ? (
                <div className="empty-state">
                    <div className="spinner"></div>
                    <div className="empty-state-text" style={{ marginTop: '1rem' }}>
                        Waiting for data... First fetch will happen shortly.
                    </div>
                </div>
            ) : (
                <>
                    <MetricsBar data={data} />
                    <GreeksBar data={data} />
                    <Chart data={data} />
                    <DataTable data={data} />
                </>
            )}
        </main>
    );
}

// Main App Component
function App() {
    const [connectionStatus, setConnectionStatus] = useState('disconnected');
    const [isTracking, setIsTracking] = useState(false);
    const [config, setConfig] = useState(null);
    const [data, setData] = useState([]);
    const wsRef = useRef(null);

    const connect = useCallback(() => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

        setConnectionStatus('connecting');
        const ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            setConnectionStatus('connected');
            console.log('WebSocket connected');
        };

        ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);

            if (msg.type === 'snapshot') {
                setData(prev => {
                    const newData = [...prev, msg];
                    // Keep only last 100 data points
                    if (newData.length > 100) {
                        return newData.slice(-100);
                    }
                    return newData;
                });
            } else if (msg.type === 'tracking_started') {
                setIsTracking(true);
            } else if (msg.type === 'tracking_stopped') {
                setIsTracking(false);
            } else if (msg.type === 'error') {
                console.error('Server error:', msg.message);
            }
        };

        ws.onclose = () => {
            setConnectionStatus('disconnected');
            setIsTracking(false);
            console.log('WebSocket disconnected');
            // Attempt to reconnect after 3 seconds
            setTimeout(connect, 3000);
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };

        wsRef.current = ws;
    }, []);

    useEffect(() => {
        connect();
        return () => {
            if (wsRef.current) {
                wsRef.current.close();
            }
        };
    }, [connect]);

    const handleStartTracking = (trackingConfig) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            setConfig(trackingConfig);
            setData([]);
            wsRef.current.send(JSON.stringify({
                action: 'start',
                ...trackingConfig
            }));
        }
    };

    const handleStopTracking = () => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ action: 'stop' }));
        }
        setIsTracking(false);
    };

    return (
        <ThemeProvider>
            <div className="app">
                <Header connectionStatus={connectionStatus} isTracking={isTracking} />
                <Sidebar
                    onStartTracking={handleStartTracking}
                    onStopTracking={handleStopTracking}
                    isTracking={isTracking}
                    isLoading={false}
                />
                <MainContent data={data} config={config} isTracking={isTracking} />
            </div>
        </ThemeProvider>
    );
}

// Render the app
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
