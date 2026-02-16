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
function Header({ connectionStatus, isTracking, sidebarVisible, onToggleSidebar, marketStatus, view, onSwitchView, onAddToWatchlist, onAddNewOption }) {
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

    const getMarketStatusText = () => {
        if (!marketStatus) return '';
        if (marketStatus.is_open) return `Market Open`;
        const statusMap = {
            'pre_market': 'Pre-Market',
            'after_market': 'After Hours',
            'closed_weekend': 'Market Closed'
        };
        return statusMap[marketStatus.status] || 'Market Closed';
    };

    const getMarketStatusClass = () => {
        if (!marketStatus) return '';
        return marketStatus.is_open ? 'connected' : '';
    };

    return (
        <header className="header">
            <div className="header-left">
                {view === 'tracker' && (
                    <button
                        className="config-toggle-btn"
                        onClick={onToggleSidebar}
                        title={sidebarVisible ? 'Hide Config' : 'Show Config'}
                    >
                        {sidebarVisible ? '\u2715' : '\u2630'}
                    </button>
                )}
                <div className="logo">
                    <svg className="logo-icon" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M3 13h1v7c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-7h1a1 1 0 0 0 .4-1.92l-9-4a1 1 0 0 0-.8 0l-9 4A1 1 0 0 0 3 13zm7 6v-4h4v4h-4zm6-4h2v4h-2v-4zM6 15h2v4H6v-4z"/>
                        <path d="M12 2L2 7l10 4.5L22 7 12 2z"/>
                    </svg>
                    Options Premium Tracker
                </div>
                <div className="view-nav">
                    <button
                        className={`view-nav-btn ${view === 'watchlist' ? 'active' : ''}`}
                        onClick={() => view !== 'watchlist' && onSwitchView()}
                    >
                        📋 Watchlist
                    </button>
                    <button
                        className={`view-nav-btn ${view === 'tracker' ? 'active' : ''}`}
                        onClick={() => view !== 'tracker' && onSwitchView()}
                    >
                        📈 Tracker
                    </button>
                    {onAddNewOption && (
                        <button
                            className="view-nav-btn add-option-btn"
                            onClick={onAddNewOption}
                        >
                            + Add Option
                        </button>
                    )}
                </div>
            </div>
            <div className="header-controls">
                {onAddToWatchlist && (
                    <button className="btn-add-watchlist" onClick={onAddToWatchlist}>
                        + Add to Watchlist
                    </button>
                )}
                {marketStatus && (
                    <div className="connection-status">
                        <span className={`status-dot ${getMarketStatusClass()}`}></span>
                        {getMarketStatusText()}
                    </div>
                )}
                {view === 'tracker' && (
                    <div className="connection-status">
                        <span className={`status-dot ${getStatusClass()}`}></span>
                        {getStatusText()}
                    </div>
                )}
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

// LocalStorage helper for form state
const FORM_STATE_KEY = 'optionsTrackerFormState';

function loadFormState() {
    try {
        const saved = localStorage.getItem(FORM_STATE_KEY);
        return saved ? JSON.parse(saved) : null;
    } catch (e) {
        return null;
    }
}

function saveFormState(state) {
    try {
        localStorage.setItem(FORM_STATE_KEY, JSON.stringify(state));
    } catch (e) {
        // Silent fail - localStorage may be unavailable
    }
}

// Sidebar Component
function Sidebar({ onStartTracking, onStopTracking, isTracking, isLoading, config, visible, onLoadHistoricalDate }) {
    const savedState = loadFormState();
    const [ticker, setTicker] = useState(savedState?.ticker || 'AAPL');
    const [putCall, setPutCall] = useState(savedState?.putCall || 'call');
    const [strikes, setStrikes] = useState([]);
    const [selectedStrike, setSelectedStrike] = useState(null);
    const [contracts, setContracts] = useState([]);
    const [selectedContract, setSelectedContract] = useState(null);
    const [stockPrice, setStockPrice] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [historicalDates, setHistoricalDates] = useState([]);

    // Save form state when values change (skip initial render)
    const hasMountedRef = useRef(false);
    useEffect(() => {
        if (!hasMountedRef.current) {
            hasMountedRef.current = true;
            return; // Skip first render
        }
        saveFormState({
            ticker,
            putCall,
            strike: selectedStrike,
            contract: selectedContract
        });
    }, [ticker, putCall, selectedStrike, selectedContract]);

    // Auto-load strikes on mount if we have saved state
    const initialLoadRef = useRef(false);
    useEffect(() => {
        const saved = loadFormState();
        if (saved?.ticker && saved?.strike && !initialLoadRef.current) {
            initialLoadRef.current = true;
            loadStrikesWithRestore();
        }
    }, []); // Run once on mount

    const loadStrikesWithRestore = async () => {
        setLoading(true);
        setError(null);
        const saved = loadFormState();

        try {
            const res = await fetch(`${API_BASE}/api/strikes/${ticker.toUpperCase()}/${putCall}`);
            if (!res.ok) throw new Error('Failed to load strikes');
            const data = await res.json();
            setStrikes(data.strikes);
            setStockPrice(data.stock_price);

            // Restore saved strike
            if (saved?.strike && data.strikes.includes(saved.strike)) {
                setSelectedStrike(saved.strike);

                // Also load contracts if we have a saved contract
                if (saved?.contract?.ticker) {
                    const contractRes = await fetch(`${API_BASE}/api/contracts/${ticker.toUpperCase()}/${saved.strike}/${putCall}`);
                    if (contractRes.ok) {
                        const contractData = await contractRes.json();
                        setContracts(contractData.contracts);
                        const matchingContract = contractData.contracts.find(c => c.ticker === saved.contract.ticker);
                        if (matchingContract) {
                            setSelectedContract(matchingContract);
                        }
                    }

                    // Also fetch historical dates for this strike/type combo
                    try {
                        const datesRes = await fetch(`${API_BASE}/api/data/dates/${ticker.toUpperCase()}/${saved.strike}/${putCall}`);
                        if (datesRes.ok) {
                            const datesData = await datesRes.json();
                            setHistoricalDates(datesData.dates || []);
                        }
                    } catch (e) {
                        console.error('Failed to fetch historical dates:', e);
                    }
                }
            }
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

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

            // Restore saved strike if it exists in the loaded strikes
            const saved = loadFormState();
            if (saved?.strike && data.strikes.includes(saved.strike)) {
                setSelectedStrike(saved.strike);
            }
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
        setHistoricalDates([]);

        try {
            const res = await fetch(`${API_BASE}/api/contracts/${ticker.toUpperCase()}/${selectedStrike}/${putCall}`);
            if (!res.ok) throw new Error('Failed to load contracts');
            const data = await res.json();
            setContracts(data.contracts);

            // Restore saved contract if it exists in the loaded contracts
            const saved = loadFormState();
            if (saved?.contract?.ticker) {
                const matchingContract = data.contracts.find(c => c.ticker === saved.contract.ticker);
                if (matchingContract) {
                    setSelectedContract(matchingContract);
                }
            }

            // Fetch historical dates for this strike/type combo
            try {
                const datesRes = await fetch(`${API_BASE}/api/data/dates/${ticker.toUpperCase()}/${selectedStrike}/${putCall}`);
                if (datesRes.ok) {
                    const datesData = await datesRes.json();
                    setHistoricalDates(datesData.dates || []);
                }
            } catch (e) {
                console.error('Failed to fetch historical dates:', e);
            }
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
        setHistoricalDates([]);
        // Clear saved form state except ticker/putCall
        saveFormState({ ticker, putCall, strike: null, contract: null });
    };

    const handleHistoricalDateClick = (dateStr) => {
        if (!selectedContract) return;
        const trackingConfig = {
            ticker: ticker.toUpperCase(),
            contract: selectedContract.ticker,
            expiration: selectedContract.expiration,
            strike: selectedStrike,
            put_call: putCall,
            dte: selectedContract.dte
        };
        onLoadHistoricalDate(trackingConfig, dateStr);
    };

    // Format date for display
    const formatDateForDisplay = (dateStr) => {
        const d = new Date(dateStr + 'T00:00:00');
        return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    };

    if (!visible) return null;

    return (
        <aside className="sidebar">
            <div className="sidebar-header">
                <span className="sidebar-title">Configuration</span>
            </div>

            <div className="sidebar-section">
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

            {selectedContract && historicalDates.length > 0 && (
                <div className="sidebar-section">
                    <div className="divider"></div>
                    <div className="sidebar-title">Historical Data</div>
                    <div className="historical-dates-list">
                        {historicalDates.map(dateStr => (
                            <button
                                key={dateStr}
                                className="historical-date-btn"
                                onClick={() => handleHistoricalDateClick(dateStr)}
                            >
                                {formatDateForDisplay(dateStr)}
                            </button>
                        ))}
                    </div>
                </div>
            )}
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

// Unified Metrics Grid Component
function MetricsGrid({ data }) {
    if (data.length === 0) return null;

    const latest = data[data.length - 1];
    const prev = data.length > 1 ? data[data.length - 2] : null;
    const od = latest.option_data;

    const getDelta = (current, previous, key) => {
        if (!previous) return null;
        return current[key] - previous[key];
    };

    const formatDelta = (delta, prefix = '$', suffix = '') => {
        if (delta === null) return null;
        const sign = delta >= 0 ? '+' : '';
        return `${sign}${prefix}${delta.toFixed(2)}${suffix}`;
    };

    const formatValue = (val, prefix = '', suffix = '', decimals = 2) => {
        if (val === null || val === undefined) return 'N/A';
        return `${prefix}${Number(val).toFixed(decimals)}${suffix}`;
    };

    const formatInt = (val) => {
        if (val === null || val === undefined) return 'N/A';
        return Number(val).toLocaleString();
    };

    const premiumDelta = getDelta(latest, prev, 'premium');
    const stockDelta = getDelta(latest, prev, 'stock_price');

    const getDeltaClass = (delta) => {
        if (delta === null || delta === 0) return 'neutral';
        return delta > 0 ? 'positive' : 'negative';
    };

    // Get last prices from data array (newest first), remove duplicates, then calculate trends
    const lastPricesWithTrend = data
        .slice()
        .reverse()
        .map(d => d.option_data?.last)
        .filter(price => price !== null && price !== undefined)
        .filter((price, index, arr) => {
            // Keep first item always, then only keep if price changed from previous
            if (index === 0) return true;
            return price !== arr[index - 1];
        })
        .map((price, index, arr) => {
            // Calculate trend based on next item in the filtered array
            const nextPrice = arr[index + 1];
            let trend = null;
            if (nextPrice !== null && nextPrice !== undefined) {
                if (price > nextPrice) trend = 'up';
                else if (price < nextPrice) trend = 'down';
            }
            return { price, trend };
        });

    return (
        <div className="metrics-grid">
            {/* Row 1: Stock Price, Premium, Last */}
            <div className="metric-cell metrics-stock">
                <div className="metric-label">Stock Price</div>
                <div className="metric-row">
                    <div className="metric-value-xl">${latest.stock_price.toFixed(2)}</div>
                    {stockDelta !== null && (
                        <div className={`metric-delta ${getDeltaClass(stockDelta)}`}>
                            {formatDelta(stockDelta)}
                        </div>
                    )}
                </div>
            </div>

            <div className="metric-cell metrics-premium">
                <div className="premium-main">
                    <div className="metric-label">Premium (Mid)</div>
                    <div className="metric-row">
                        <div className="metric-value-xl">${latest.premium.toFixed(2)}</div>
                        {premiumDelta !== null && (
                            <div className={`metric-delta ${getDeltaClass(premiumDelta)}`}>
                                {formatDelta(premiumDelta)}
                            </div>
                        )}
                    </div>
                </div>
                <div className="premium-bidask">
                    <div className="bidask-row">
                        <span className="bidask-label">BID</span>
                        <span className="bidask-value">{formatValue(od.bid, '$')}</span>
                    </div>
                    <div className="bidask-row">
                        <span className="bidask-label">ASK</span>
                        <span className="bidask-value">{formatValue(od.ask, '$')}</span>
                    </div>
                </div>
            </div>

            {/* Last: col 5, spans both rows */}
            <div className="metric-cell metrics-last">
                <div className="metric-label">Last</div>
                <div className="last-price-list">
                    {lastPricesWithTrend.map((item, i) => (
                        <div key={i} className={`last-price-item ${item.trend || ''}`}>
                            <span>${item.price.toFixed(2)}</span>
                            {item.trend === 'up' && <span className="trend-arrow up">▲</span>}
                            {item.trend === 'down' && <span className="trend-arrow down">▼</span>}
                        </div>
                    ))}
                </div>
            </div>

            {/* Row 2: Spread %, IV, Volume, Open Int */}
            <div className="metric-cell metrics-greek">
                <div className="greek-label">Spread %</div>
                <div className="greek-value">{latest.spread_pct.toFixed(2)}%</div>
            </div>
            <div className="metric-cell metrics-greek">
                <div className="greek-label">IV</div>
                <div className="greek-value">{od.iv ? formatValue(od.iv * 100, '', '%', 1) : 'N/A'}</div>
            </div>
            <div className="metric-cell metrics-greek">
                <div className="greek-label">Volume</div>
                <div className="greek-value">{formatInt(od.volume)}</div>
            </div>
            <div className="metric-cell metrics-greek">
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
            }
        ];

        const layout = {
            xaxis: {
                showgrid: true,
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 10 }
            },
            yaxis: {
                title: { text: 'Premium ($)', font: { color: colors.text, size: 11 } },
                showgrid: true,
                gridcolor: colors.grid,
                tickfont: { color: colors.text, size: 10 },
                side: 'left'
            },
            yaxis2: {
                title: { text: 'Stock Price ($)', font: { color: colors.text, size: 11 } },
                showgrid: false,
                tickfont: { color: colors.text, size: 10 },
                side: 'right',
                overlaying: 'y'
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
            <div ref={chartRef} style={{ width: '100%', height: '100%', minHeight: '250px' }}></div>
        </div>
    );
}

// Data Table Toggle Header (separate component for header row layout)
function DataTableToggleHeader({ isOpen, onToggle }) {
    return (
        <div className="data-table-toggle-header" onClick={onToggle}>
            <span className="data-table-title">Raw Data</span>
            <span className={`data-table-toggle ${isOpen ? 'open' : ''}`}>
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                    <path d="M2 4l4 4 4-4z"/>
                </svg>
            </span>
        </div>
    );
}

// Data Table Component
function DataTable({ data, isOpen }) {
    if (data.length === 0 || !isOpen) return null;

    // Show all data when expanded (reversed so newest first)
    const displayData = [...data].reverse();

    return (
        <div className="data-table-container expanded">
            <div className="data-table-body">
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
            </div>
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

// Helper to get today's date string
function getTodayStr() {
    return new Date().toISOString().split('T')[0];
}

// Day Navigator Component
function DayNavigator({ selectedDate, availableDates, onDateChange, isTracking, config }) {
    if (!config) return null;

    const todayStr = getTodayStr();
    const isToday = selectedDate === todayStr;

    // Sort dates for navigation (oldest to newest)
    const sortedDates = [...availableDates].sort();

    const currentIndex = sortedDates.indexOf(selectedDate);
    const hasPrev = currentIndex > 0;
    const hasNext = currentIndex < sortedDates.length - 1 || !isToday;

    const handlePrev = () => {
        if (hasPrev && !isTracking) {
            onDateChange(sortedDates[currentIndex - 1]);
        }
    };

    const handleNext = () => {
        if (!isTracking) {
            if (currentIndex < sortedDates.length - 1) {
                onDateChange(sortedDates[currentIndex + 1]);
            } else if (!isToday) {
                // Go to today even if no data exists yet
                onDateChange(todayStr);
            }
        }
    };

    const handleToday = () => {
        if (!isTracking && !isToday) {
            onDateChange(todayStr);
        }
    };

    // Format date for display
    const formatDate = (dateStr) => {
        const d = new Date(dateStr + 'T00:00:00');
        return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    };

    return (
        <div className="day-navigator">
            <button
                className="day-nav-btn"
                onClick={handlePrev}
                disabled={!hasPrev || isTracking}
                title="Previous day"
            >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                    <path d="M8 2l-4 4 4 4z"/>
                </svg>
            </button>
            <div className="day-nav-date">
                <span className="day-nav-date-text">{formatDate(selectedDate)}</span>
                {isToday && <span className="day-nav-today-badge">Today</span>}
            </div>
            <button
                className="day-nav-btn"
                onClick={handleNext}
                disabled={(!hasNext && isToday) || isTracking}
                title="Next day"
            >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                    <path d="M4 2l4 4-4 4z"/>
                </svg>
            </button>
            {!isToday && (
                <button
                    className="day-nav-today-btn"
                    onClick={handleToday}
                    disabled={isTracking}
                    title="Jump to today"
                >
                    Today
                </button>
            )}
            {isTracking && (
                <span className="day-nav-live-badge">LIVE</span>
            )}
        </div>
    );
}

// Main Content Component
function MainContent({ data, config, isTracking, selectedDate, availableDates, onDateChange }) {
    const [isDataTableOpen, setIsDataTableOpen] = useState(false);

    if (!config) {
        return (
            <main className="main">
                <EmptyState />
            </main>
        );
    }

    const todayStr = getTodayStr();
    const isViewingToday = selectedDate === todayStr;

    return (
        <main className="main">
            <ContractInfo config={config} />
            {data.length === 0 && isTracking && isViewingToday ? (
                <>
                    <div className="empty-state">
                        <div className="spinner"></div>
                        <div className="empty-state-text" style={{ marginTop: '1rem' }}>
                            Waiting for data... First fetch will happen shortly.
                        </div>
                    </div>
                    <div className="chart-footer-row">
                        <DayNavigator
                            selectedDate={selectedDate}
                            availableDates={availableDates}
                            onDateChange={onDateChange}
                            isTracking={isTracking}
                            config={config}
                        />
                    </div>
                </>
            ) : data.length === 0 ? (
                <>
                    <div className="empty-state">
                        <div className="empty-state-icon">📅</div>
                        <div className="empty-state-text">
                            No data for this date.
                        </div>
                    </div>
                    <div className="chart-footer-row">
                        <DayNavigator
                            selectedDate={selectedDate}
                            availableDates={availableDates}
                            onDateChange={onDateChange}
                            isTracking={isTracking}
                            config={config}
                        />
                    </div>
                </>
            ) : (
                <>
                    <MetricsGrid data={data} />
                    <div className="chart-data-wrapper">
                        {/* Chart is hidden when data table is expanded */}
                        {!isDataTableOpen && <Chart data={data} />}
                        {/* Footer row with Day Navigator and Raw Data toggle side by side */}
                        <div className="chart-footer-row">
                            {!isDataTableOpen && (
                                <DayNavigator
                                    selectedDate={selectedDate}
                                    availableDates={availableDates}
                                    onDateChange={onDateChange}
                                    isTracking={isTracking}
                                    config={config}
                                />
                            )}
                            <DataTableToggleHeader
                                isOpen={isDataTableOpen}
                                onToggle={() => setIsDataTableOpen(!isDataTableOpen)}
                            />
                        </div>
                        {/* Data table body expands to fill space when open */}
                        <DataTable data={data} isOpen={isDataTableOpen} />
                    </div>
                </>
            )}
        </main>
    );
}

// Watchlist Row Component
function WatchlistRow({ item, onRemove, onTrack }) {
    const [snapshot, setSnapshot] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Fetch snapshot data for this option
    useEffect(() => {
        const fetchSnapshot = async () => {
            try {
                setLoading(true);
                const res = await fetch(`${API_BASE}/api/watchlist/${item.id}/snapshot`);
                const data = await res.json();
                if (data.error) {
                    setError(data.error);
                } else {
                    setSnapshot(data);
                }
            } catch (e) {
                setError(e.message);
            } finally {
                setLoading(false);
            }
        };

        fetchSnapshot();
        // Refresh every 60 seconds
        const interval = setInterval(fetchSnapshot, 60000);
        return () => clearInterval(interval);
    }, [item.id]);

    // Calculate DTE
    const calculateDTE = (expiration) => {
        const exp = new Date(expiration);
        const today = new Date();
        const diffTime = exp - today;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        return diffDays;
    };

    const dte = calculateDTE(item.expiration);

    const handleRowClick = () => {
        onTrack(item);
    };

    const handleRemove = (e) => {
        e.stopPropagation();
        if (confirm(`Remove ${item.ticker} $${item.strike.toFixed(2)} ${item.put_call.toUpperCase()} from watchlist?`)) {
            onRemove(item.id);
        }
    };

    return (
        <tr className="watchlist-row" onClick={handleRowClick}>
            <td className="cell-ticker">{item.ticker}</td>
            <td className="cell-strike">${item.strike.toFixed(2)}</td>
            <td className="cell-type">
                <span className={`type-badge type-${item.put_call}`}>
                    {item.put_call.toUpperCase()}
                </span>
            </td>
            <td className="cell-expiration">{item.expiration}</td>
            <td className="cell-dte">{dte}</td>
            <td className="cell-price">
                {loading ? (
                    <div className="spinner-small"></div>
                ) : error ? (
                    <span className="price-error">—</span>
                ) : snapshot ? (
                    snapshot.option_data.last !== null
                        ? `$${snapshot.option_data.last.toFixed(2)}`
                        : '—'
                ) : '—'}
            </td>
            <td className="cell-price">
                {loading ? '' : error ? '—' : snapshot ? `$${snapshot.option_data.bid.toFixed(2)}` : '—'}
            </td>
            <td className="cell-price">
                {loading ? '' : error ? '—' : snapshot ? `$${snapshot.option_data.ask.toFixed(2)}` : '—'}
            </td>
            <td className="cell-remove">
                <button
                    className="remove-btn"
                    onClick={handleRemove}
                    title="Remove from watchlist"
                >
                    ✕
                </button>
            </td>
        </tr>
    );
}

// Watchlist Table Header Component
function WatchlistTableHeader({ sortBy, sortDirection, onSort }) {
    const columns = [
        { key: 'ticker', label: 'Ticker', type: 'string' },
        { key: 'strike', label: 'Strike', type: 'number' },
        { key: 'type', label: 'Type', type: 'string' },
        { key: 'expiration', label: 'Expiration', type: 'string' },
        { key: 'dte', label: 'DTE', type: 'number' },
        { key: null, label: 'Last', type: null }, // Not sortable
        { key: null, label: 'Bid', type: null }, // Not sortable
        { key: null, label: 'Ask', type: null }, // Not sortable
        { key: null, label: '', type: null }, // Remove button column
    ];

    const handleSort = (key) => {
        if (!key) return; // Skip non-sortable columns
        if (sortBy === key) {
            onSort(key, sortDirection === 'asc' ? 'desc' : 'asc');
        } else {
            onSort(key, 'asc');
        }
    };

    const getSortIcon = (key) => {
        if (!key) return null;
        if (sortBy !== key) return <span className="sort-icon"></span>;
        return <span className={`sort-icon ${sortDirection}`}></span>;
    };

    return (
        <thead>
            <tr>
                {columns.map((col, idx) => (
                    <th
                        key={idx}
                        className={col.key ? 'sortable' : ''}
                        data-sort={col.key || ''}
                        data-type={col.type || ''}
                        onClick={() => handleSort(col.key)}
                    >
                        <span className="th-content">
                            {col.label}
                            {getSortIcon(col.key)}
                        </span>
                    </th>
                ))}
            </tr>
        </thead>
    );
}

// Watchlist View Component
function WatchlistView({ onSwitchToTracker }) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [sortBy, setSortBy] = useState('ticker'); // default sort
    const [sortDirection, setSortDirection] = useState('asc');

    // Load watchlist
    useEffect(() => {
        const loadWatchlist = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/watchlist`);
                const data = await res.json();
                setItems(data.items || []);
            } catch (e) {
                console.error('Failed to load watchlist:', e);
            } finally {
                setLoading(false);
            }
        };
        loadWatchlist();
    }, []);

    // Helper to calculate DTE
    const calculateDTE = (expiration) => {
        const exp = new Date(expiration);
        const today = new Date();
        const diffTime = exp - today;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        return diffDays;
    };

    // Sort items based on current sort settings
    const sortedItems = [...items].sort((a, b) => {
        let compareValue = 0;

        switch (sortBy) {
            case 'ticker':
                compareValue = a.ticker.localeCompare(b.ticker);
                break;
            case 'dte':
                const dtea = calculateDTE(a.expiration);
                const dteb = calculateDTE(b.expiration);
                compareValue = dtea - dteb;
                break;
            case 'strike':
                compareValue = a.strike - b.strike;
                break;
            case 'type':
                compareValue = a.put_call.localeCompare(b.put_call);
                break;
            default:
                compareValue = 0;
        }

        return sortDirection === 'asc' ? compareValue : -compareValue;
    });

    const handleSort = (key, direction) => {
        setSortBy(key);
        setSortDirection(direction);
    };

    const handleRemove = async (itemId) => {
        try {
            await fetch(`${API_BASE}/api/watchlist/${itemId}`, {
                method: 'DELETE',
            });
            setItems(items.filter(item => item.id !== itemId));
        } catch (e) {
            console.error('Failed to remove item:', e);
            alert('Failed to remove option from watchlist. Please try again.');
        }
    };

    const handleTrack = (item) => {
        // Switch to tracker view with this item's config
        onSwitchToTracker({
            ticker: item.ticker,
            strike: item.strike,
            put_call: item.put_call,
            expiration: item.expiration,
            contract: item.contract,
        });
    };

    if (loading) {
        return (
            <main className="main">
                <div className="empty-state">
                    <div className="spinner"></div>
                    <div className="empty-state-text">Loading watchlist...</div>
                </div>
            </main>
        );
    }

    if (items.length === 0) {
        return (
            <main className="main">
                <div className="empty-state">
                    <div className="empty-state-icon">📊</div>
                    <div className="empty-state-text">
                        Your watchlist is empty. Add options to track their premiums.
                    </div>
                    <button className="btn-primary" onClick={() => onSwitchToTracker(null)}>
                        Add Your First Option
                    </button>
                </div>
            </main>
        );
    }

    return (
        <main className="main">
            <div className="watchlist-table-container">
                <table className="watchlist-table">
                    <WatchlistTableHeader
                        sortBy={sortBy}
                        sortDirection={sortDirection}
                        onSort={handleSort}
                    />
                    <tbody>
                        {sortedItems.map(item => (
                            <WatchlistRow
                                key={item.id}
                                item={item}
                                onRemove={handleRemove}
                                onTrack={handleTrack}
                            />
                        ))}
                    </tbody>
                </table>
            </div>
        </main>
    );
}

// Main App Component
function App() {
    const [view, setView] = useState('watchlist'); // 'watchlist' or 'tracker'
    const [connectionStatus, setConnectionStatus] = useState('disconnected');
    const [isTracking, setIsTracking] = useState(false);
    const [config, setConfig] = useState(null);
    const [data, setData] = useState([]);
    const [sidebarVisible, setSidebarVisible] = useState(true);
    const [marketStatus, setMarketStatus] = useState(null);
    const [selectedDate, setSelectedDate] = useState(getTodayStr);
    const [availableDates, setAvailableDates] = useState([]);
    const wsRef = useRef(null);
    const configRef = useRef(null); // Track current config for saving snapshots
    const selectedDateRef = useRef(selectedDate); // For closure in onmessage

    // Keep selectedDateRef in sync
    useEffect(() => {
        selectedDateRef.current = selectedDate;
    }, [selectedDate]);

    // Fetch market status on mount and every 5 minutes
    useEffect(() => {
        const fetchMarketStatus = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/market/status`);
                const status = await res.json();
                setMarketStatus(status);
            } catch (e) {
                console.error('Failed to fetch market status:', e);
            }
        };

        fetchMarketStatus();
        const interval = setInterval(fetchMarketStatus, 300000); // 5 minutes
        return () => clearInterval(interval);
    }, []);

    // Auto-hide sidebar when tracking starts
    useEffect(() => {
        if (isTracking) {
            setSidebarVisible(false);
        }
    }, [isTracking]);

    // Save snapshot to server
    const saveSnapshot = useCallback(async (snapshot, trackingConfig) => {
        if (!trackingConfig) return;
        try {
            await fetch(`${API_BASE}/api/data/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...snapshot,
                    ticker: trackingConfig.ticker,
                    strike: trackingConfig.strike,
                    put_call: trackingConfig.put_call
                })
            });
        } catch (e) {
            console.error('Failed to save snapshot:', e);
        }
    }, []);

    // Load saved data from server
    const loadSavedData = useCallback(async (trackingConfig, dateStr = null) => {
        try {
            const dateParam = dateStr ? `?date=${dateStr}` : '';
            const res = await fetch(
                `${API_BASE}/api/data/load/${trackingConfig.ticker}/${trackingConfig.strike}/${trackingConfig.put_call}${dateParam}`
            );
            const data = await res.json();
            return data.snapshots || [];
        } catch (e) {
            console.error('Failed to load saved data:', e);
            return [];
        }
    }, []);

    // Fetch available dates for a contract
    const fetchAvailableDates = useCallback(async (trackingConfig) => {
        try {
            const res = await fetch(
                `${API_BASE}/api/data/dates/${trackingConfig.ticker}/${trackingConfig.strike}/${trackingConfig.put_call}`
            );
            const data = await res.json();
            return data.dates || [];
        } catch (e) {
            console.error('Failed to fetch available dates:', e);
            return [];
        }
    }, []);

    // Handle date change from day navigator
    const handleDateChange = useCallback(async (newDate) => {
        if (!config) return;
        setSelectedDate(newDate);
        const savedData = await loadSavedData(config, newDate);
        setData(savedData);
    }, [config, loadSavedData]);

    // Handle loading historical date from sidebar
    const handleLoadHistoricalDate = useCallback(async (trackingConfig, dateStr) => {
        setConfig(trackingConfig);
        configRef.current = trackingConfig;
        setSelectedDate(dateStr);
        selectedDateRef.current = dateStr;

        // Fetch available dates for this contract
        const dates = await fetchAvailableDates(trackingConfig);
        const todayStr = getTodayStr();
        if (!dates.includes(todayStr)) {
            dates.unshift(todayStr);
        }
        setAvailableDates(dates);

        // Load saved data for the selected date
        const savedData = await loadSavedData(trackingConfig, dateStr);
        setData(savedData);

        // Hide sidebar after loading
        setSidebarVisible(false);
    }, [fetchAvailableDates, loadSavedData]);

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
                // Save snapshot to file
                saveSnapshot(msg, configRef.current);

                // Only append to UI if viewing today (use ref to avoid stale closure)
                const todayStr = getTodayStr();
                if (selectedDateRef.current === todayStr) {
                    setData(prev => {
                        const newData = [...prev, msg];
                        return newData;
                    });
                }
            } else if (msg.type === 'tracking_started') {
                setIsTracking(true);
            } else if (msg.type === 'tracking_stopped') {
                setIsTracking(false);
                // If stopped due to market closing, update market status
                if (msg.market_status) {
                    setMarketStatus(msg.market_status);
                }
                if (msg.message) {
                    console.log('Tracking stopped:', msg.message);
                }
            } else if (msg.type === 'market_closed') {
                // Update market status when we get this message
                setMarketStatus(msg.market_status);
                console.log('Market closed:', msg.message);
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
    }, [saveSnapshot]);

    useEffect(() => {
        connect();
        return () => {
            if (wsRef.current) {
                wsRef.current.close();
            }
        };
    }, [connect]);

    // Handle clicking outside sidebar to close it
    useEffect(() => {
        const handleClickOutside = (event) => {
            if (sidebarVisible) {
                const sidebar = document.querySelector('.sidebar');
                const headerToggle = document.querySelector('.config-toggle-btn');
                
                // Close sidebar if click is outside sidebar and not on the header toggle button
                if (sidebar && !sidebar.contains(event.target) && !headerToggle.contains(event.target)) {
                    setSidebarVisible(false);
                }
            }
        };

        if (sidebarVisible) {
            document.addEventListener('mousedown', handleClickOutside);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [sidebarVisible]);

    const handleStartTracking = async (trackingConfig) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            setConfig(trackingConfig);
            configRef.current = trackingConfig;

            // Reset to today when starting tracking
            const todayStr = getTodayStr();
            setSelectedDate(todayStr);
            selectedDateRef.current = todayStr;

            // Fetch available dates for this contract
            const dates = await fetchAvailableDates(trackingConfig);
            // Ensure today is in the list (even if no data yet)
            if (!dates.includes(todayStr)) {
                dates.unshift(todayStr);
            }
            setAvailableDates(dates);

            // Load saved data for today BEFORE starting tracking
            console.log('Loading saved data for:', trackingConfig, 'date:', todayStr);
            const savedData = await loadSavedData(trackingConfig, todayStr);
            console.log('Loaded', savedData.length, 'snapshots from file');

            // Load all saved data for today
            setData(savedData);

            // Now start real-time tracking which will append to this data
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

    const handleSwitchToTracker = (itemConfig) => {
        setView('tracker');
        setSidebarVisible(true);
        
        // If itemConfig is provided, pre-populate the form
        if (itemConfig) {
            // The Sidebar will need to handle this pre-population
            // For now, just switch to tracker view
        }
    };

    const handleSwitchToWatchlist = () => {
        setView('watchlist');
        setSidebarVisible(false);
        if (isTracking) {
            handleStopTracking();
        }
    };

    const handleAddToWatchlist = async () => {
        if (!config) return;
        
        try {
            await fetch(`${API_BASE}/api/watchlist`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker: config.ticker,
                    strike: config.strike,
                    put_call: config.put_call,
                    expiration: config.expiration,
                    contract: config.contract,
                })
            });
            alert('Added to watchlist!');
        } catch (e) {
            console.error('Failed to add to watchlist:', e);
            alert('Failed to add to watchlist');
        }
    };

    return (
        <ThemeProvider>
            <div className="app">
                <Header
                    connectionStatus={connectionStatus}
                    isTracking={isTracking}
                    sidebarVisible={sidebarVisible}
                    onToggleSidebar={() => setSidebarVisible(!sidebarVisible)}
                    marketStatus={marketStatus}
                    view={view}
                    onSwitchView={view === 'watchlist' ? handleSwitchToTracker : handleSwitchToWatchlist}
                    onAddToWatchlist={view === 'tracker' && config ? handleAddToWatchlist : null}
                    onAddNewOption={view === 'watchlist' ? () => handleSwitchToTracker(null) : null}
                />
                {view === 'watchlist' ? (
                    <WatchlistView onSwitchToTracker={handleSwitchToTracker} />
                ) : (
                    <>
                        <Sidebar
                            onStartTracking={handleStartTracking}
                            onStopTracking={handleStopTracking}
                            isTracking={isTracking}
                            isLoading={false}
                            config={config}
                            visible={sidebarVisible}
                            onLoadHistoricalDate={handleLoadHistoricalDate}
                        />
                        <MainContent
                            data={data}
                            config={config}
                            isTracking={isTracking}
                            selectedDate={selectedDate}
                            availableDates={availableDates}
                            onDateChange={handleDateChange}
                        />
                    </>
                )}
            </div>
        </ThemeProvider>
    );
}

// Render the app
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
