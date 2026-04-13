const { useState, useEffect, useRef, useCallback, createContext, useContext } = React;

// API Configuration
const API_BASE = '';  // Same origin - will use current host

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
        bid: '#00cc00',
        ask: '#00cc00',
        bandFill: 'rgba(0, 255, 0, 0.12)',
        mid: '#00ff00',
        stock: '#ffb000',
        lastTrade: '#00aaff',
        spread: '#ff3333',
        grid: '#222222',
        bg: '#111111',
        text: '#ffffff',
        hoverlabel: { bgcolor: '#111111', font: { color: '#ffffff' } }
    },
    fintech: {
        bid: '#10b981',
        ask: '#10b981',
        bandFill: 'rgba(16, 185, 129, 0.15)',
        mid: '#10b981',
        stock: '#a78bfa',
        lastTrade: '#f59e0b',
        spread: '#ef4444',
        grid: '#2a2a38',
        bg: '#1c1c26',
        text: '#ffffff',
        hoverlabel: { bgcolor: '#1c1c26', font: { color: '#ffffff' } }
    },
    retro: {
        bid: '#c9a800',
        ask: '#c9a800',
        bandFill: 'rgba(255, 215, 0, 0.1)',
        mid: '#ffd700',
        stock: '#39ff14',
        lastTrade: '#00aaff',
        spread: '#ff3366',
        grid: '#1a1a40',
        bg: '#12122e',
        text: '#ffd700',
        hoverlabel: { bgcolor: '#12122e', font: { color: '#ffd700' } }
    },
    swiss: {
        bid: '#cc0000',
        ask: '#cc0000',
        bandFill: 'rgba(255, 0, 0, 0.08)',
        mid: '#ff0000',
        stock: '#000000',
        lastTrade: '#3b82f6',
        spread: '#888888',
        grid: '#dddddd',
        bg: '#ffffff',
        text: '#000000',
        hoverlabel: { bgcolor: '#ffffff', font: { color: '#000000' } }
    }
};

// Black-Scholes pricing
const RISK_FREE_RATE = 0.045; // ~current risk-free rate

function normCDF(x) {
    // Rational approximation of cumulative normal distribution
    const a1 = 0.254829592, a2 = -0.284496736, a3 = 1.421413741;
    const a4 = -1.453152027, a5 = 1.061405429, p = 0.3275911;
    const sign = x < 0 ? -1 : 1;
    x = Math.abs(x) / Math.SQRT2;
    const t = 1.0 / (1.0 + p * x);
    const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
    return 0.5 * (1.0 + sign * y);
}

function blackScholes(S, K, T, sigma, putCall) {
    // S=stock, K=strike, T=years to expiry, sigma=IV, putCall='call'|'put'
    if (T <= 0) return Math.max(0, putCall === 'call' ? S - K : K - S); // intrinsic at expiry
    if (!sigma || sigma <= 0 || !S || S <= 0) return null;

    const d1 = (Math.log(S / K) + (RISK_FREE_RATE + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T));
    const d2 = d1 - sigma * Math.sqrt(T);

    if (putCall === 'call') {
        return S * normCDF(d1) - K * Math.exp(-RISK_FREE_RATE * T) * normCDF(d2);
    } else {
        return K * Math.exp(-RISK_FREE_RATE * T) * normCDF(-d2) - S * normCDF(-d1);
    }
}

// Header Component
function Header({ marketStatus }) {
    const { theme, setTheme } = useTheme();
    const themes = ['bloomberg', 'fintech', 'retro', 'swiss'];

    // Retro theme Easter egg: pixel character walks across the header
    useEffect(() => {
        if (theme !== 'retro') return;

        const spawnWalker = () => {
            const header = document.querySelector('.header');
            if (!header) return;

            const goRight = Math.random() > 0.5;
            const walker = document.createElement('div');
            walker.className = 'retro-walker';

            // Pick a random character
            const characters = [
                { frames: ['🍄', '🍄'], bob: true, facesLeft: false },
                { frames: ['🏃', '🚶'], bob: false, facesLeft: true },
                { frames: ['⭐', '✨'], bob: true, facesLeft: false },
                { frames: ['👾', '👾'], bob: true, facesLeft: false },
            ];
            const char = characters[Math.floor(Math.random() * characters.length)];

            walker.textContent = char.frames[0];
            // Flip if the character faces the wrong way for its direction
            const needsFlip = char.facesLeft ? goRight : !goRight;
            walker.style.cssText = `
                position: absolute;
                top: 50%;
                transform: translateY(-50%) ${needsFlip ? 'scaleX(-1)' : ''};
                font-size: 20px;
                z-index: 100;
                pointer-events: none;
                ${goRight ? 'left: -30px' : 'right: -30px'};
                filter: drop-shadow(0 0 4px #ffd700);
            `;

            header.style.position = 'relative';
            header.style.overflow = 'hidden';
            header.appendChild(walker);

            const duration = 6000 + Math.random() * 4000;
            const startTime = Date.now();
            let frameIdx = 0;

            const animate = () => {
                const elapsed = Date.now() - startTime;
                const progress = elapsed / duration;

                if (progress >= 1) {
                    walker.remove();
                    return;
                }

                const headerWidth = header.offsetWidth + 60;
                const pos = progress * headerWidth - 30;

                if (goRight) {
                    walker.style.left = pos + 'px';
                } else {
                    walker.style.right = pos + 'px';
                }

                // Walking bob
                if (char.bob) {
                    const bob = Math.sin(elapsed / 120) * 2;
                    walker.style.transform = `translateY(calc(-50% + ${bob}px)) ${needsFlip ? 'scaleX(-1)' : ''}`;
                }

                // Alternate frames
                if (Math.floor(elapsed / 300) !== frameIdx) {
                    frameIdx = Math.floor(elapsed / 300);
                    walker.textContent = char.frames[frameIdx % char.frames.length];
                }

                requestAnimationFrame(animate);
            };

            requestAnimationFrame(animate);
        };

        // Spawn at random intervals between 30s and 90s
        let timeout;
        const scheduleNext = () => {
            const delay = 30000 + Math.random() * 60000;
            timeout = setTimeout(() => {
                spawnWalker();
                scheduleNext();
            }, delay);
        };

        // First one after 5-15 seconds
        timeout = setTimeout(() => {
            spawnWalker();
            scheduleNext();
        }, 5000 + Math.random() * 10000);

        return () => clearTimeout(timeout);
    }, [theme]);

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
                <div className="logo">
                    <svg className="logo-icon" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M3 13h1v7c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-7h1a1 1 0 0 0 .4-1.92l-9-4a1 1 0 0 0-.8 0l-9 4A1 1 0 0 0 3 13zm7 6v-4h4v4h-4zm6-4h2v4h-2v-4zM6 15h2v4H6v-4z"/>
                        <path d="M12 2L2 7l10 4.5L22 7 12 2z"/>
                    </svg>
                    Options Premium Tracker
                </div>
            </div>
            <div className="header-controls">
                {marketStatus && (
                    <div className="connection-status">
                        <span className={`status-dot ${getMarketStatusClass()}`}></span>
                        {getMarketStatusText()}
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
function Sidebar({ onStartTracking, onStopTracking, isTracking, isLoading, config, visible }) {
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
                if (saved?.contract?.contract_symbol) {
                    const contractRes = await fetch(`${API_BASE}/api/contracts/${ticker.toUpperCase()}/${saved.strike}/${putCall}`);
                    if (contractRes.ok) {
                        const contractData = await contractRes.json();
                        setContracts(contractData.contracts);
                        const matchingContract = contractData.contracts.find(c => c.contract_symbol === saved.contract.contract_symbol);
                        if (matchingContract) {
                            setSelectedContract(matchingContract);
                        }
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
            if (!data.strikes || data.strikes.length === 0) {
                setError('No options found for this ticker. Check the symbol or try again.');
            } else {
                setStrikes(data.strikes);
                setStockPrice(data.stock_price);

                // Restore saved strike if it exists in the loaded strikes
                const saved = loadFormState();
                if (saved?.strike && data.strikes.includes(saved.strike)) {
                    setSelectedStrike(saved.strike);
                }
            }
        } catch (e) {
            setError(`Failed to load strikes: ${e.message}`);
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

            // Restore saved contract if it exists in the loaded contracts
            const saved = loadFormState();
            if (saved?.contract?.contract_symbol) {
                const matchingContract = data.contracts.find(c => c.contract_symbol === saved.contract.contract_symbol);
                if (matchingContract) {
                    setSelectedContract(matchingContract);
                }
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
            contract: selectedContract.contract_symbol,
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
        // Clear saved form state except ticker/putCall
        saveFormState({ ticker, putCall, strike: null, contract: null });
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
                            value={selectedContract ? selectedContract.contract_symbol : ''}
                            onChange={e => {
                                const c = contracts.find(c => c.contract_symbol === e.target.value);
                                setSelectedContract(c);
                            }}
                            disabled={isTracking}
                        >
                            <option value="">Select expiration...</option>
                            {contracts.map(c => (
                                <option key={c.contract_symbol} value={c.contract_symbol}>
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
const Chart = React.memo(function Chart({ data, selectedDate }) {
    const chartRef = useRef(null);
    const { theme } = useTheme();
    const colors = chartColors[theme];

    useEffect(() => {
        if (!chartRef.current || data.length === 0) return;
        renderPriceChart(chartRef.current, data, selectedDate, colors);
    }, [data, theme]);

    if (data.length === 0) return null;

    return (
        <div className="chart-container">
            <div className="chart-title">Premium & Stock Price</div>
            <div ref={chartRef} style={{ width: '100%', height: '100%', minHeight: '250px' }}></div>
        </div>
    );
});

function renderPriceChart(el, data, selectedDate, colors) {
    const timestamps = data.map(d => new Date(d.timestamp));
    const bids = data.map(d => d.option_data ? d.option_data.bid : null);
    const asks = data.map(d => d.option_data ? d.option_data.ask : null);
    const lasts = data.map(d => d.option_data ? d.option_data.last : null);
    const stockPrices = data.map(d => d.stock_price);

    const isMultiDay = !selectedDate;
    let xRange;
    let noDataBreaks = [];
    if (isMultiDay) {
        xRange = undefined;
        // Detect weekdays with no data and collapse them from the axis
        const tradingDays = new Set(timestamps.map(t => t.toLocaleDateString('en-CA')));
        if (timestamps.length > 0) {
            const start = new Date(timestamps[0]);
            const end = new Date(timestamps[timestamps.length - 1]);
            for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
                if (d.getDay() === 0 || d.getDay() === 6) continue;
                const dateStr = d.toLocaleDateString('en-CA');
                if (!tradingDays.has(dateStr)) {
                    noDataBreaks.push(dateStr + ' 09:30');
                }
            }
        }
    } else {
        const dateForAxis = selectedDate || timestamps[timestamps.length - 1].toLocaleDateString('en-CA');
        xRange = [new Date(`${dateForAxis}T09:30:00`), new Date(`${dateForAxis}T16:00:00`)];
    }

    const tradingWindowMs = 6.5 * 60 * 60 * 1000;

    const traces = [
        { x: timestamps, y: bids, name: 'Bid / Ask', type: 'scatter', mode: 'lines',
          line: { color: colors.mid, width: 2 }, connectgaps: true },
        { x: timestamps, y: asks, name: 'Ask', type: 'scatter', mode: 'lines',
          line: { color: colors.mid, width: 2 }, fill: 'tonexty', fillcolor: colors.bandFill,
          connectgaps: true, showlegend: false },
        { x: timestamps, y: stockPrices, name: 'Stock Price', type: 'scatter', mode: 'lines',
          line: { color: colors.stock, width: 1.5 }, yaxis: 'y2' },
        { x: timestamps, y: lasts, name: 'Last Trade', type: 'scatter', mode: 'lines+markers',
          marker: { size: 3, color: colors.lastTrade }, line: { color: colors.lastTrade, width: 1 }, connectgaps: false }
    ];

    const layout = {
        xaxis: {
            type: 'date', range: xRange, autorange: isMultiDay ? true : undefined,
            showgrid: true, gridcolor: colors.grid, tickfont: { color: colors.text, size: 10 },
            rangebreaks: isMultiDay ? [
                { bounds: [16, 9.5], pattern: 'hour' },
                { bounds: ['sat', 'mon'], pattern: 'day of week' },
                ...(noDataBreaks.length > 0 ? [{ values: noDataBreaks, dvalue: tradingWindowMs }] : [])
            ] : []
        },
        yaxis: { title: { text: 'Price ($)', font: { color: colors.text, size: 11 } },
                 showgrid: true, gridcolor: colors.grid, tickfont: { color: colors.text, size: 10 }, side: 'left' },
        yaxis2: { title: { text: 'Stock Price ($)', font: { color: colors.text, size: 11 } },
                  showgrid: false, tickfont: { color: colors.text, size: 10 }, side: 'right', overlaying: 'y' },
        paper_bgcolor: 'transparent', plot_bgcolor: colors.bg, font: { color: colors.text },
        hoverlabel: colors.hoverlabel,
        legend: { orientation: 'h', y: 1.12, x: 0.5, xanchor: 'center', font: { size: 11 } },
        margin: { l: 60, r: 60, t: 30, b: 40 }, hovermode: 'x unified'
    };

    Plotly.react(el, traces, layout, { responsive: true, displayModeBar: false });
}

function renderThetaDecayChart(el, data, item, colors) {
    const expDate = new Date(item.expiration + 'T16:00:00');
    const strike = Number(item.strike);
    const putCall = item.put_call;

    // Find the initial IV (fixed) from first snapshot — this stays constant
    let initialIV = null;
    for (let i = 0; i < data.length; i++) {
        const iv = data[i].option_data ? data[i].option_data.iv : null;
        if (iv && iv > 0) { initialIV = iv; break; }
    }

    // Collect actual last trade prices AND theoretical (fixed IV, actual stock) at each snapshot
    const actualDTE = [];
    const actualPrices = [];
    const theoDTE = [];
    const theoPrices = [];

    data.forEach(d => {
        const snapDate = new Date(d.timestamp);
        const daysToExp = Math.max(0, (expDate - snapDate) / (1000 * 60 * 60 * 24));
        const last = d.option_data ? d.option_data.last : null;
        const stockPrice = d.stock_price;

        // Actual last trade
        if (last != null) {
            actualDTE.push(daysToExp);
            actualPrices.push(last);
        }

        // Theoretical: fixed IV from entry + actual stock price at this moment
        if (initialIV && stockPrice) {
            const T = daysToExp / 365.25;
            const bs = blackScholes(stockPrice, strike, T, initialIV, putCall);
            if (bs != null) {
                theoDTE.push(daysToExp);
                theoPrices.push(Math.round(bs * 100) / 100);
            }
        }
    });

    // Project theoretical forward to expiration using latest stock price + fixed IV
    let latestStock = null;
    for (let i = data.length - 1; i >= 0; i--) {
        if (data[i].stock_price) { latestStock = data[i].stock_price; break; }
    }

    const projDTE = [];
    const projPrices = [];
    const nowDTE = Math.max(0, (expDate - new Date()) / (1000 * 60 * 60 * 24));

    if (initialIV && latestStock) {
        for (let d = nowDTE; d >= 0; d -= 0.25) {
            const T = d / 365.25;
            const bs = blackScholes(latestStock, strike, T, initialIV, putCall);
            if (bs != null) {
                projDTE.push(d);
                projPrices.push(Math.round(bs * 100) / 100);
            }
        }
        if (projDTE.length > 0 && projDTE[projDTE.length - 1] > 0) {
            projDTE.push(0);
            const intrinsic = putCall === 'call' ? Math.max(0, latestStock - strike) : Math.max(0, strike - latestStock);
            projPrices.push(intrinsic);
        }
    }

    const maxDTE = Math.max(
        actualDTE.length > 0 ? Math.max(...actualDTE) : 0,
        theoDTE.length > 0 ? Math.max(...theoDTE) : 0
    );

    // Build gap fill between actual and theoretical (shaded IV impact area)
    const gapDTE = [], gapUpper = [], gapLower = [];
    actualDTE.forEach((d, i) => {
        // Find closest theoretical point
        let closestIdx = 0, closestDist = Infinity;
        theoDTE.forEach((td, ti) => {
            const dist = Math.abs(td - d);
            if (dist < closestDist) { closestDist = dist; closestIdx = ti; }
        });
        if (closestDist < 0.5 && theoPrices[closestIdx] != null && actualPrices[i] != null) {
            gapDTE.push(d);
            gapUpper.push(Math.max(actualPrices[i], theoPrices[closestIdx]));
            gapLower.push(Math.min(actualPrices[i], theoPrices[closestIdx]));
        }
    });

    const traces = [
        // IV impact gap fill
        { x: gapDTE, y: gapLower, type: 'scatter', mode: 'lines',
          line: { color: 'transparent', width: 0 }, showlegend: false, hoverinfo: 'skip' },
        { x: gapDTE, y: gapUpper, type: 'scatter', mode: 'lines',
          fill: 'tonexty', fillcolor: 'rgba(255,204,0,0.10)', name: 'IV Impact',
          line: { color: 'transparent', width: 0 },
          hoverinfo: 'skip' },
        // Theoretical (fixed IV, actual stock price)
        { x: theoDTE, y: theoPrices, name: 'Theoretical (Fixed IV)',
          type: 'scatter', mode: 'lines',
          line: { color: colors.lastTrade, width: 2.5, dash: 'dash' },
          hovertemplate: 'DTE: %{x:.1f}<br>Theoretical: $%{y:.2f}<extra></extra>' },
        // Projected decay (from now to expiration)
        { x: projDTE, y: projPrices, name: 'Projected',
          type: 'scatter', mode: 'lines',
          line: { color: colors.lastTrade, width: 1.5, dash: 'dot' },
          opacity: 0.6, showlegend: false,
          hovertemplate: 'DTE: %{x:.1f}<br>Projected: $%{y:.2f}<extra></extra>' },
        // Actual last trade prices
        { x: actualDTE, y: actualPrices, name: 'Actual (Last)',
          type: 'scatter', mode: 'lines+markers',
          line: { color: colors.mid, width: 2 },
          marker: { size: 3, color: colors.mid },
          hovertemplate: 'DTE: %{x:.1f}<br>Last: $%{y:.2f}<extra></extra>' },
    ];

    const layout = {
        xaxis: {
            title: { text: 'Days to Expiration', font: { color: colors.text, size: 11 } },
            showgrid: true, gridcolor: colors.grid,
            tickfont: { color: colors.text, size: 10 },
            range: [Math.ceil(maxDTE) + 1, -0.5]
        },
        yaxis: {
            title: { text: 'Option Premium ($)', font: { color: colors.text, size: 11 } },
            showgrid: true, gridcolor: colors.grid,
            tickfont: { color: colors.text, size: 10 },
            tickprefix: '$', side: 'left'
        },
        shapes: [
            // "Now" vertical line — bold and visible
            { type: 'line', x0: nowDTE, x1: nowDTE, y0: 0, y1: 1, yref: 'paper',
              line: { color: '#ff3333', width: 2.5 } }
        ],
        annotations: [
            { x: nowDTE, y: 1.02, yref: 'paper', xanchor: 'left', text: '  NOW',
              showarrow: false, font: { color: '#ff3333', size: 11, family: 'var(--font-mono), monospace' } }
        ],
        paper_bgcolor: 'transparent', plot_bgcolor: colors.bg, font: { color: colors.text },
        hoverlabel: colors.hoverlabel,
        legend: { orientation: 'h', y: 1.12, x: 0.5, xanchor: 'center', font: { size: 11 } },
        margin: { l: 60, r: 30, t: 30, b: 50 }, hovermode: 'x unified'
    };

    Plotly.react(el, traces, layout, { responsive: true, displayModeBar: false });
}

// Helpers for formatting nullable numbers
const fmt = (v, decimals = 2) => v != null ? Number(v).toFixed(decimals) : '—';
const fmtIV = (v) => v != null ? (v * 100).toFixed(1) + '%' : '—';

// Map a raw DB/SSE snapshot to the shape expected by Chart and DataTable
function mapSnapshot(s) {
    return {
        timestamp: s.timestamp,
        premium: s.mid,
        stock_price: s.stock_price,
        spread_pct: s.spread_pct,
        option_data: {
            bid: s.bid, ask: s.ask, mid: s.mid,
            last: s.last_price, volume: s.volume,
            open_interest: s.open_interest, iv: s.implied_volatility,
            delta: s.delta, gamma: s.gamma, theta: s.theta, vega: s.vega,
        }
    };
}

// Data Table Toggle Header (separate component for header row layout)
function DataTableToggleHeader({ isOpen, onToggle, selectedDate, availableDates, onDateChange, dte, activeTimeframe, onTimeframeSelect }) {
    const is1D = activeTimeframe === 1;
    const hasDates = is1D && availableDates && availableDates.length > 0 && selectedDate;
    const idx = hasDates ? availableDates.indexOf(selectedDate) : -1;
    const isToday = selectedDate === new Date().toLocaleDateString('en-CA');

    const fmt = (d) => {
        const dt = new Date(d + 'T12:00:00');
        return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    };

    // Build timeframe buttons: [15D][7D][1D]
    const frames = [
        { label: '15D', value: 15 },
        { label: '7D', value: 7 },
        { label: '1D', value: 1 },
    ];

    return (
        <div className="data-table-toggle-header">
            <div className="footer-left">
                <div className="timeframe-buttons">
                    {frames.map(f => (
                        <button
                            key={f.value}
                            className={`timeframe-btn${activeTimeframe === f.value ? ' active' : ''}${f.value === 'dte' ? ' dte-btn' : ''}`}
                            onClick={e => { e.stopPropagation(); onTimeframeSelect(f.value); }}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
                {hasDates && (
                    <div className="date-nav-inline">
                        <button className="date-nav-inline-btn"
                            onClick={e => { e.stopPropagation(); onDateChange(availableDates[idx - 1]); }}
                            disabled={idx <= 0}>←</button>
                        <span className="date-nav-inline-label">
                            {fmt(selectedDate)}{isToday ? ' · Today' : ''}
                        </span>
                        <button className="date-nav-inline-btn"
                            onClick={e => { e.stopPropagation(); onDateChange(availableDates[idx + 1]); }}
                            disabled={idx >= availableDates.length - 1}>→</button>
                    </div>
                )}
            </div>
            <div className="date-nav-toggle-right" onClick={onToggle}>
                <span className="data-table-title">Raw Data</span>
                <span className={`data-table-toggle ${isOpen ? 'open' : ''}`}>
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                        <path d="M2 4l4 4 4-4z"/>
                    </svg>
                </span>
            </div>
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
                            <th>Mid ($)</th>
                            <th>Last ($)</th>
                            <th>Bid ($)</th>
                            <th>Ask ($)</th>
                            <th>Stock ($)</th>
                            <th>Spread (%)</th>
                            <th>Volume</th>
                            <th>OI</th>
                            <th>IV %</th>
                        </tr>
                    </thead>
                    <tbody>
                        {displayData.map((d, i) => {
                            const od = d.option_data;
                            return (
                                <tr key={i}>
                                    <td>{new Date(d.timestamp).toLocaleTimeString()}</td>
                                    <td>{fmt(d.premium)}</td>
                                    <td>{fmt(od?.last)}</td>
                                    <td>{fmt(od?.bid)}</td>
                                    <td>{fmt(od?.ask)}</td>
                                    <td>{fmt(d.stock_price)}</td>
                                    <td>{fmt(d.spread_pct)}</td>
                                    <td>{fmt(od?.volume, 0)}</td>
                                    <td>{fmt(od?.open_interest, 0)}</td>
                                    <td>{fmtIV(od?.iv)}</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// Timeframe Selector Component
function TimeframeSelector({ dte, activeTimeframe, onSelect, selectedDate, availableDates, onDateChange }) {
    // Build button list: [DTE][30][7][1] — DTE only if different from 30/7/1
    const standardFrames = [30, 7, 1];
    const frames = [];

    // Add DTE button if it's different from all standard frames and > 0
    if (dte > 0 && !standardFrames.includes(dte)) {
        frames.push({ label: `${dte}D`, value: dte, isDTE: true });
    }

    // Add standard frames (only if <= DTE or it's 1D which always shows)
    standardFrames.forEach(f => {
        frames.push({ label: `${f}D`, value: f });
    });

    // Sort descending by value
    frames.sort((a, b) => b.value - a.value);

    // For 1D mode, show date nav arrows
    const is1D = activeTimeframe === 1;
    const hasDates = is1D && availableDates && availableDates.length > 0 && selectedDate;
    const idx = hasDates ? availableDates.indexOf(selectedDate) : -1;
    const isToday = selectedDate === new Date().toLocaleDateString('en-CA');

    const fmtDate = (d) => {
        const dt = new Date(d + 'T12:00:00');
        return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    };

    return (
        <div className="timeframe-bar">
            <div className="timeframe-buttons">
                {frames.map(f => (
                    <button
                        key={f.value}
                        className={`timeframe-btn${activeTimeframe === f.value ? ' active' : ''}${f.isDTE ? ' dte-btn' : ''}`}
                        onClick={e => { e.stopPropagation(); onSelect(f.value); }}
                    >
                        {f.label}
                    </button>
                ))}
            </div>
            {hasDates && (
                <div className="date-nav-inline">
                    <button className="date-nav-inline-btn"
                        onClick={e => { e.stopPropagation(); onDateChange(availableDates[idx - 1]); }}
                        disabled={idx <= 0}>←</button>
                    <span className="date-nav-inline-label">
                        {fmtDate(selectedDate)}{isToday ? ' · Today' : ''}
                    </span>
                    <button className="date-nav-inline-btn"
                        onClick={e => { e.stopPropagation(); onDateChange(availableDates[idx + 1]); }}
                        disabled={idx >= availableDates.length - 1}>→</button>
                </div>
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
function MainContent({ data, config, isTracking }) {
    const [isDataTableOpen, setIsDataTableOpen] = useState(false);

    if (!config) {
        return (
            <main className="main">
                <EmptyState />
            </main>
        );
    }

    const todayStr = getTodayStr();
    const isViewingToday = true; // Always viewing latest data now

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
                    {/* Day Navigator removed - using real-time data only */}
                </>
            ) : data.length === 0 ? (
                <>
                    <div className="empty-state">
                        <div className="empty-state-icon">📅</div>
                        <div className="empty-state-text">
                            No data available yet.
                        </div>
                    </div>
                    {/* Day Navigator removed - using real-time data only */}
                </>
            ) : (
                <>
                    <MetricsGrid data={data} />
                    <div className="chart-data-wrapper">
                        {/* Chart is hidden when data table is expanded */}
                        {!isDataTableOpen && <Chart data={data} />}
                        {/* Footer row with Raw Data toggle */}
                        <div className="chart-footer-row">
                            {/* Day Navigator removed - using real-time data only */}
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
function WatchlistRow({ item, onRemove, onDragStart, onDragOver, onDragEnd, onDrop, isDragging, isDropped, dragOverId }) {
    const [snapshot, setSnapshot] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [historyData, setHistoryData] = useState([]);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [isDataTableOpen, setIsDataTableOpen] = useState(false);
    const [selectedDate, setSelectedDate] = useState(null);
    const [activeTimeframe, setActiveTimeframe] = useState(1); // 1 = 1D, 7 = 7D, 15 = 15D, 'dte' = theta decay

    // Fetch snapshot data for this option
    useEffect(() => {
        let isInitialFetch = true;
        const fetchSnapshot = async () => {
            try {
                if (isInitialFetch) setLoading(true);
                const res = await fetch(`${API_BASE}/api/watchlist/${item.id}/snapshot`);
                const data = await res.json();
                if (data.error) {
                    setError(data.error);
                } else {
                    setSnapshot(data);
                    setError(null);
                }
            } catch (e) {
                setError(e.message);
            } finally {
                setLoading(false);
                isInitialFetch = false;
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

    const handleRowClick = async () => {
        if (expanded) { setExpanded(false); return; }
        setExpanded(true);
        setHistoryLoading(true);
        try {
            const res = await fetch(`${API_BASE}/api/snapshots/${item.id}?limit=5000`);
            const raw = await res.json();
            // Map MySQL fields → Chart/DataTable shape, reverse to oldest-first
            const mapped = raw.map(mapSnapshot).reverse();
            setHistoryData(mapped);
            // Default to today if data exists for today, else most recent date
            const today = new Date().toLocaleDateString('en-CA');
            const dates = [...new Set(mapped.map(d => d.timestamp.slice(0, 10)))].sort();
            setSelectedDate(dates.includes(today) ? today : dates[dates.length - 1]);
        } finally {
            setHistoryLoading(false);
        }
    };

    // SSE: append new snapshots to the chart in real-time while the row is expanded
    useEffect(() => {
        if (!expanded) return;
        const sse = new EventSource(`${API_BASE}/sse/option/${item.id}`);
        sse.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (!data.snapshot) return;
                const s = data.snapshot;
                const newPoint = mapSnapshot(s);
                setHistoryData(prev => {
                    if (prev.length === 0) return [newPoint];
                    const last = prev[prev.length - 1];
                    if (last.timestamp === newPoint.timestamp) return prev;
                    return [...prev, newPoint];
                });
            } catch(e) {}
        };
        return () => sse.close();
    }, [expanded, item.id]);

    // Periodic re-fetch: detect backfill/gap-fill inserts and reload chart data
    useEffect(() => {
        if (!expanded) return;
        const countRef = { current: historyData.length };
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/api/snapshots/${item.id}?limit=5000`);
                const raw = await res.json();
                if (raw.length > countRef.current) {
                    countRef.current = raw.length;
                    const mapped = raw.map(mapSnapshot).reverse();
                    setHistoryData(mapped);
                }
            } catch(e) {}
        }, 60000);
        return () => clearInterval(interval);
    }, [expanded, item.id]);

    const [confirmingRemove, setConfirmingRemove] = useState(false);
    const confirmTimerRef = useRef(null);

    const handleRemove = (e) => {
        e.stopPropagation();
        if (!confirmingRemove) {
            setConfirmingRemove(true);
            confirmTimerRef.current = setTimeout(() => setConfirmingRemove(false), 3000);
        } else {
            clearTimeout(confirmTimerRef.current);
            setConfirmingRemove(false);
            onRemove(item.id);
        }
    };

    // Derived: available dates and filtered data based on active timeframe
    const availableDates = [...new Set(historyData.map(d => d.timestamp.slice(0, 10)))].sort();

    const filteredData = (() => {
        if (historyData.length === 0) return [];

        if (activeTimeframe === 1) {
            // 1D mode: single day, market hours only (existing behavior)
            if (!selectedDate) return [];
            return historyData.filter(d => {
                if (!d.timestamp.startsWith(selectedDate)) return false;
                const t = new Date(d.timestamp);
                const mins = t.getHours() * 60 + t.getMinutes();
                return mins >= 9 * 60 && mins < 16 * 60;
            });
        }

        // Multi-day mode: filter to last N days from today
        const now = new Date();
        const cutoff = new Date(now);
        cutoff.setDate(cutoff.getDate() - activeTimeframe);
        return historyData.filter(d => {
            const t = new Date(d.timestamp);
            return t >= cutoff;
        });
    })();

    return (
        <>
            <tr
                className={`watchlist-row${expanded ? ' expanded' : ''}${isDragging ? ' dragging' : ''}${dragOverId === item.id ? ' drag-over' : ''}${isDropped ? ' just-dropped' : ''}`}
                onClick={handleRowClick}
                onDragOver={onDragOver ? (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; onDragOver(item.id); } : undefined}
                onDrop={onDrop ? (e) => { e.preventDefault(); onDrop(item.id); } : undefined}
                onDragEnd={onDragEnd || undefined}
            >
                <td
                    className="cell-drag"
                    draggable={!!onDragStart}
                    onClick={e => e.stopPropagation()}
                    onDragStart={onDragStart ? (e) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setDragImage(e.target.closest('tr'), 0, 0); onDragStart(item.id); } : undefined}
                >
                    {onDragStart ? <span className="drag-handle">☰</span> : null}
                </td>
                <td className="cell-ticker">{item.ticker}</td>
                <td className="cell-strike">${item.strike != null ? Number(item.strike).toFixed(2) : '—'}</td>
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
                    {loading ? '' : error ? '—' : snapshot ? (snapshot.option_data.bid !== null && snapshot.option_data.bid !== undefined ? `$${snapshot.option_data.bid.toFixed(2)}` : '—') : '—'}
                </td>
                <td className="cell-price">
                    {loading ? '' : error ? '—' : snapshot ? (snapshot.option_data.ask !== null && snapshot.option_data.ask !== undefined ? `$${snapshot.option_data.ask.toFixed(2)}` : '—') : '—'}
                </td>
                <td className="cell-remove">
                    <button
                        className={`remove-btn ${confirmingRemove ? 'remove-confirming' : ''}`}
                        onClick={handleRemove}
                        title={confirmingRemove ? 'Click again to confirm' : 'Remove from watchlist'}
                    >
                        {confirmingRemove ? 'Sure?' : '✕'}
                    </button>
                </td>
            </tr>
            {expanded && (
                <tr className="watchlist-row-detail">
                    <td colSpan={10}>
                        <div className="row-history-panel">
                            {historyLoading ? (
                                <div className="spinner"></div>
                            ) : historyData.length === 0 ? (
                                <div className="empty-state-text">No history yet.</div>
                            ) : (
                                <>
                                    <Chart data={filteredData} selectedDate={activeTimeframe === 1 ? selectedDate : null} />
                                    <div className="chart-footer-row">
                                        <DataTableToggleHeader
                                            isOpen={isDataTableOpen}
                                            onToggle={() => setIsDataTableOpen(o => !o)}
                                            selectedDate={selectedDate}
                                            availableDates={availableDates}
                                            onDateChange={setSelectedDate}
                                            dte={dte}
                                            activeTimeframe={activeTimeframe}
                                            onTimeframeSelect={setActiveTimeframe}
                                        />
                                    </div>
                                    <DataTable data={filteredData} isOpen={isDataTableOpen} />
                                </>
                            )}
                        </div>
                    </td>
                </tr>
            )}
        </>
    );
}

// Watchlist Table Header Component
function WatchlistTableHeader({ onSort }) {
    const columns = [
        { key: null, label: '', type: null, className: 'col-drag' }, // Drag handle column
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

    const [lastSort, setLastSort] = useState({ key: null, dir: 'asc' });

    const handleSort = (key) => {
        if (!key) return;
        const dir = lastSort.key === key && lastSort.dir === 'asc' ? 'desc' : 'asc';
        setLastSort({ key, dir });
        onSort(key, dir);
    };

    const getSortIcon = (key) => {
        if (!key) return null;
        if (lastSort.key !== key) return <span className="sort-icon"></span>;
        return <span className={`sort-icon ${lastSort.dir}`}></span>;
    };

    return (
        <thead>
            <tr>
                {columns.map((col, idx) => (
                    <th
                        key={idx}
                        className={`${col.key ? 'sortable' : ''} ${col.className || ''}`}
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

// Custom strike dropdown — centers the selected (ATM) option when opened
function StrikeSelect({ strikes, value, onChange, disabled, stockPrice, putCall, stale }) {
    const [open, setOpen] = useState(false);
    const containerRef = useRef(null);
    const listRef = useRef(null);
    const ITEM_H = 28;

    // Close on outside click
    useEffect(() => {
        if (!open) return;
        const handler = (e) => {
            if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [open]);

    // Scroll selected item to center when list opens
    useEffect(() => {
        if (!open || !listRef.current || !value) return;
        const idx = strikes.indexOf(parseFloat(value));
        if (idx < 0) return;
        const list = listRef.current;
        const itemTop = idx * ITEM_H;
        list.scrollTop = itemTop - list.clientHeight / 2 + ITEM_H / 2;
    }, [open]);

    const label = value ? `$${parseFloat(value).toFixed(2)}` : `Strike ${strikes.length === 0 ? '—' : '▾'}`;

    return (
        <div ref={containerRef} style={{ position: 'relative', flex: '1 1 0px', minWidth: 0 }}>
            <button
                type="button"
                className="quick-add-select"
                style={{
                    width: '100%', textAlign: 'left', cursor: disabled ? 'not-allowed' : 'pointer',
                    opacity: disabled ? 0.5 : stale ? 0.45 : 1, display: 'flex', justifyContent: 'space-between',
                    alignItems: 'center'
                }}
                disabled={disabled}
                onClick={() => !disabled && strikes.length > 0 && setOpen(o => !o)}
            >
                <span>{label}</span>
                {strikes.length > 0 && <span style={{ opacity: 0.6, fontSize: '0.75em' }}>▾</span>}
            </button>
            {open && (
                <div
                    ref={listRef}
                    style={{
                        position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 1000,
                        maxHeight: `${ITEM_H * 10}px`, overflowY: 'auto',
                        background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                        borderRadius: '4px', boxShadow: '0 4px 16px rgba(0,0,0,0.4)'
                    }}
                >
                    {strikes.map(s => {
                        const isOtm = stockPrice ? (putCall === 'call' ? s < stockPrice : s > stockPrice) : false;
                        const isSelected = String(s) === String(value);
                        return (
                            <div
                                key={s}
                                style={{
                                    height: `${ITEM_H}px`, lineHeight: `${ITEM_H}px`,
                                    padding: '0 10px', cursor: 'pointer', fontSize: '0.85em',
                                    backgroundColor: isSelected
                                        ? 'var(--accent-primary)'
                                        : (stale || isOtm) ? '#444' : 'var(--bg-card)',
                                    color: isSelected
                                        ? 'var(--bg-primary)'
                                        : (stale || isOtm) ? '#aaa' : 'var(--text-primary)',
                                    userSelect: 'none'
                                }}
                                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.opacity = '0.8'; }}
                                onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
                                onMouseDown={e => {
                                    e.preventDefault();
                                    onChange(String(s));
                                    setOpen(false);
                                }}
                            >
                                ${s.toFixed(2)}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

// Quick-Add Card Component
function QuickAddCard({ onAdded }) {
    const [ticker, setTicker] = useState('');
    const [putCall, setPutCall] = useState('call');
    const [strikes, setStrikes] = useState([]);
    const [selectedStrike, setSelectedStrike] = useState('');
    const [contracts, setContracts] = useState([]);
    const [selectedContract, setSelectedContract] = useState('');
    const [status, setStatus] = useState('idle'); // idle | loading-strikes | strikes | loading-contracts | contracts | adding
    const [error, setError] = useState(null);
    const [stockPrice, setStockPrice] = useState(null);
    const [strikesStale, setStrikesStale] = useState(false);

    const isLoading = status === 'loading-strikes' || status === 'loading-contracts' || status === 'adding';

    const loadContracts = async (tickerVal, strikeVal, pc) => {
        const resolvedPc = pc || putCall;
        setStatus('loading-contracts');
        setContracts([]);
        setSelectedContract('');
        try {
            const res = await fetch(`${API_BASE}/api/contracts/${tickerVal}/${strikeVal}/${resolvedPc}`);
            if (!res.ok) throw new Error('Failed to load contracts');
            const data = await res.json();
            setContracts(data.contracts || []);
            setStatus('contracts');
        } catch (e) {
            setError(e.message);
            setStatus('strikes');
        }
    };

    const loadStrikes = async (putCallVal) => {
        const pc = putCallVal || putCall;
        const t = ticker.trim().toUpperCase();
        if (!t) return;
        setStrikesStale(false);
        setStatus('loading-strikes');
        setError(null);
        setStrikes([]);
        setSelectedStrike('');
        setContracts([]);
        setSelectedContract('');

        try {
            const res = await fetch(`${API_BASE}/api/strikes/${t}/${pc}`);
            if (!res.ok) throw new Error('Failed to load strikes');
            const data = await res.json();
            if (!data.strikes || data.strikes.length === 0) {
                throw new Error('No options found for this ticker');
            }
            const strikesArr = data.strikes;
            const price = data.stock_price || null;
            setStockPrice(price);
            setStrikes(strikesArr);
            setStatus('strikes');

            // Pre-select closest strike to stock price and auto-load contracts
            if (strikesArr.length > 0 && price) {
                const closest = strikesArr.reduce((a, b) =>
                    Math.abs(b - price) < Math.abs(a - price) ? b : a
                );
                setSelectedStrike(String(closest));
                loadContracts(t, closest, pc);
            }
        } catch (e) {
            setError(e.message);
            setStatus('idle');
        }
    };

    const handleTickerKeyDown = (e) => {
        if (e.key === 'Enter' && ticker.trim()) {
            loadStrikes();
        }
    };

    const handleStrikeChange = (strike) => {
        setSelectedStrike(strike);
        setContracts([]);
        setSelectedContract('');

        if (!strike) {
            setStatus('strikes');
            return;
        }

        setError(null);
        loadContracts(ticker.trim().toUpperCase(), strike, putCall);
    };

    const handleAdd = async () => {
        if (!selectedContract) return;
        const contract = contracts.find(c => c.contract_symbol === selectedContract);
        if (!contract) return;

        setStatus('adding');
        setError(null);

        try {
            const res = await fetch(`${API_BASE}/api/watchlist`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ticker: ticker.trim().toUpperCase(),
                    strike: parseFloat(selectedStrike),
                    put_call: putCall,
                    expiration: contract.expiration,
                    contract_symbol: contract.contract_symbol
                })
            });
            if (!res.ok) throw new Error('Failed to add to watchlist');

            // Reset to idle
            setTicker('');
            setPutCall('call');
            setStrikes([]);
            setSelectedStrike('');
            setContracts([]);
            setSelectedContract('');
            setStatus('idle');
            onAdded();
        } catch (e) {
            setError(e.message);
            setStatus('contracts');
        }
    };

    return (
        <div className="quick-add-card">
            <div className="quick-add-row">
                <input
                    type="text"
                    className="quick-add-ticker"
                    value={ticker}
                    onChange={e => { setTicker(e.target.value.toUpperCase()); if (strikes.length > 0) setStrikesStale(true); }}
                    onKeyDown={handleTickerKeyDown}
                    placeholder="Type a ticker & press Enter"
                    disabled={isLoading}
                />
                <div className="quick-add-putcall">
                    <button
                        className={`putcall-btn ${putCall === 'call' ? 'active' : ''}`}
                        onClick={() => { if (putCall === 'call' && strikes.length > 0 && !strikesStale) return; setPutCall('call'); if (ticker.trim()) loadStrikes('call'); }}
                        disabled={isLoading}
                    >CALL</button>
                    <button
                        className={`putcall-btn ${putCall === 'put' ? 'active' : ''}`}
                        onClick={() => { if (putCall === 'put' && strikes.length > 0 && !strikesStale) return; setPutCall('put'); if (ticker.trim()) loadStrikes('put'); }}
                        disabled={isLoading}
                    >PUT</button>
                </div>
                <StrikeSelect
                    strikes={strikes}
                    value={selectedStrike}
                    onChange={handleStrikeChange}
                    disabled={isLoading}
                    stockPrice={stockPrice}
                    putCall={putCall}
                    stale={strikesStale}
                />
                <select
                    className="quick-add-select"
                    value={selectedContract}
                    onChange={e => setSelectedContract(e.target.value)}
                    disabled={isLoading || contracts.length === 0}
                >
                    <option value="">DTE {contracts.length === 0 ? '—' : '▾'}</option>
                    {contracts.map(c => (
                        <option key={c.contract_symbol} value={c.contract_symbol}>
                            {c.expiration} ({c.dte}d)
                        </option>
                    ))}
                </select>
                <button
                    className="quick-add-btn"
                    onClick={handleAdd}
                    disabled={isLoading || !selectedContract}
                >
                    {status === 'adding' ? <span className="spinner-small"></span> : '+ Add'}
                </button>
            </div>
            {error && <div className="quick-add-error">{error}</div>}
            {status === 'loading-strikes' && <div className="quick-add-hint">Loading strikes...</div>}
        </div>
    );
}

// Watchlist View Component
const WATCHLIST_ORDER_KEY = 'optionsTrackerWatchlistOrder';

function WatchlistView() {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [dragItemId, setDragItemId] = useState(null);
    const [dragOverItemId, setDragOverItemId] = useState(null);
    const [droppedItemId, setDroppedItemId] = useState(null);
    const eventSourceRef = useRef(null);

    // Apply saved order to items
    const applyCustomOrder = (itemList) => {
        try {
            const saved = localStorage.getItem(WATCHLIST_ORDER_KEY);
            if (!saved) return itemList;
            const order = JSON.parse(saved);
            const orderMap = {};
            order.forEach((id, idx) => orderMap[id] = idx);
            return [...itemList].sort((a, b) => {
                const posA = orderMap[a.id] !== undefined ? orderMap[a.id] : 9999;
                const posB = orderMap[b.id] !== undefined ? orderMap[b.id] : 9999;
                return posA - posB;
            });
        } catch { return itemList; }
    };

    const saveOrder = (itemList) => {
        try {
            localStorage.setItem(WATCHLIST_ORDER_KEY, JSON.stringify(itemList.map(i => i.id)));
        } catch {}
    };

    // SSE connection for real-time watchlist updates
    useEffect(() => {
        // Initial load
        const loadWatchlist = async () => {
            try {
                const res = await fetch(`${API_BASE}/api/watchlist`);
                const data = await res.json();
                setItems(applyCustomOrder(data || []));
                setLoading(false);
            } catch (e) {
                console.error('Failed to load watchlist:', e);
                setLoading(false);
            }
        };
        loadWatchlist();

        // Setup SSE for real-time updates
        const eventSource = new EventSource(`${API_BASE}/sse/watchlist`);
        
        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const ordered = applyCustomOrder(data || []);
                const newJson = JSON.stringify(ordered);
                setItems(prev => JSON.stringify(prev) === newJson ? prev : ordered);
            } catch (e) {
                console.error('Failed to parse SSE data:', e);
            }
        };
        
        eventSource.onerror = (error) => {
            console.error('SSE error:', error);
            eventSource.close();
        };
        
        eventSourceRef.current = eventSource;

        // Cleanup on unmount
        return () => {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
            }
        };
    }, []);

    // Helper to calculate DTE
    const calculateDTE = (expiration) => {
        const exp = new Date(expiration);
        const today = new Date();
        const diffTime = exp - today;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        return diffDays;
    };

    const sortedItems = applyCustomOrder(items);

    const handleSort = (key, direction) => {
        // Sort the items, save as new custom order, stay in drag mode
        const sorted = [...items].sort((a, b) => {
            let cmp = 0;
            switch (key) {
                case 'ticker': cmp = a.ticker.localeCompare(b.ticker); break;
                case 'dte': cmp = calculateDTE(a.expiration) - calculateDTE(b.expiration); break;
                case 'strike': cmp = a.strike - b.strike; break;
                case 'type': cmp = a.put_call.localeCompare(b.put_call); break;
                default: cmp = 0;
            }
            return direction === 'asc' ? cmp : -cmp;
        });
        saveOrder(sorted);
        setItems(sorted);
    };

    // Drag-and-drop handlers (only active when in custom order mode)
    const handleDragStart = (id) => setDragItemId(id);
    const handleDragOver = (id) => { if (id !== dragItemId) setDragOverItemId(id); };
    const handleDragEnd = () => { setDragItemId(null); setDragOverItemId(null); };
    const handleDrop = (targetId) => {
        if (!dragItemId || dragItemId === targetId) { handleDragEnd(); return; }
        const ordered = applyCustomOrder(items);
        const dragIdx = ordered.findIndex(i => i.id === dragItemId);
        const targetIdx = ordered.findIndex(i => i.id === targetId);
        if (dragIdx === -1 || targetIdx === -1) { handleDragEnd(); return; }
        const reordered = [...ordered];
        const [moved] = reordered.splice(dragIdx, 1);
        reordered.splice(targetIdx, 0, moved);
        saveOrder(reordered);
        setItems(reordered);
        setDroppedItemId(dragItemId);
        setTimeout(() => setDroppedItemId(null), 850);
        handleDragEnd();
    };

    const refreshWatchlist = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/watchlist`);
            const data = await res.json();
            const ordered = applyCustomOrder(data || []);
            // Save order so new items get a position
            saveOrder(ordered);
            setItems(ordered);
        } catch (e) {
            console.error('Failed to refresh watchlist:', e);
        }
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
                <QuickAddCard onAdded={refreshWatchlist} />
                <div className="watchlist-empty-text">
                    Your watchlist is empty.
                </div>
            </main>
        );
    }

    return (
        <main className="main">
            <QuickAddCard onAdded={refreshWatchlist} />
            <div className="watchlist-table-container">
                <table className="watchlist-table">
                    <WatchlistTableHeader onSort={handleSort} />
                    <tbody>
                        {sortedItems.map(item => (
                            <WatchlistRow
                                key={item.id}
                                item={item}
                                onRemove={handleRemove}
                                onDragStart={handleDragStart}
                                onDragOver={handleDragOver}
                                onDragEnd={handleDragEnd}
                                onDrop={handleDrop}
                                isDragging={dragItemId === item.id}
                                isDropped={droppedItemId === item.id}
                                dragOverId={dragOverItemId}
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
    const [marketStatus, setMarketStatus] = useState(null);

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
        const interval = setInterval(fetchMarketStatus, 60000); // 1 minute
        return () => clearInterval(interval);
    }, []);

    return (
        <ThemeProvider>
            <div className="app">
                <Header marketStatus={marketStatus} />
                <WatchlistView />
                <DataSourceBadge source={marketStatus?.data_source} />
            </div>
        </ThemeProvider>
    );
}

function DataSourceBadge({ source }) {
    if (!source) return null;
    const isSchwab = source === 'schwab';
    return (
        <div className="data-source-badge">
            Powered by {isSchwab ? 'Charles Schwab' : 'yfinance'}
        </div>
    );
}

// Render the app
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
