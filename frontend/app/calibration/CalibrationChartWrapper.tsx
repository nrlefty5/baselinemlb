'use client'

import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Line,
  ComposedChart,
  Area,
} from 'recharts'

interface CalibrationBucket {
  range: string
  lower: number
  upper: number
  midpoint: number
  total: number
  hits: number
  hitRate: number
}

interface CalibrationChartWrapperProps {
  buckets: CalibrationBucket[]
}

// Custom tooltip for the calibration chart
function CustomTooltip({ active, payload }: any) {
  if (!active || !payload || payload.length === 0) return null
  const data = payload[0].payload

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm shadow-lg">
      <p className="text-slate-300 font-medium mb-1">{data.range} confidence</p>
      <p className="text-blue-400">Actual accuracy: {data.hitRate}%</p>
      <p className="text-slate-400">Expected: {data.midpoint}%</p>
      <p className="text-slate-500 text-xs mt-1">n = {data.total} predictions</p>
      {(() => {
        const dev = data.hitRate - data.midpoint
        const color = Math.abs(dev) <= 5 ? 'text-green-400' : Math.abs(dev) <= 10 ? 'text-yellow-400' : 'text-red-400'
        return <p className={`text-xs ${color}`}>Deviation: {dev > 0 ? '+' : ''}{dev.toFixed(1)}%</p>
      })()}
    </div>
  )
}

// Custom dot renderer with size based on sample count
function CustomDot(props: any) {
  const { cx, cy, payload } = props
  if (!cx || !cy) return null

  // Size proportional to sample count (min 6, max 16)
  const maxTotal = 500 // rough cap
  const radius = Math.max(6, Math.min(16, 6 + (payload.total / maxTotal) * 10))

  // Color based on deviation from expected
  const deviation = Math.abs(payload.hitRate - payload.midpoint)
  const fill = deviation <= 5 ? '#22c55e' : deviation <= 10 ? '#3b82f6' : deviation <= 15 ? '#f59e0b' : '#ef4444'

  return (
    <circle
      cx={cx}
      cy={cy}
      r={radius}
      fill={fill}
      stroke={fill}
      strokeWidth={2}
      fillOpacity={0.7}
    />
  )
}

export default function CalibrationChartWrapper({ buckets }: CalibrationChartWrapperProps) {
  // Format data for Recharts
  const chartData = buckets.map(b => ({
    ...b,
    expected: b.midpoint,
  }))

  // Perfect calibration line data points
  const perfectLine = [
    { midpoint: 50, hitRate: 50 },
    { midpoint: 95, hitRate: 95 },
  ]

  return (
    <div className="w-full h-[400px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          margin={{ top: 10, right: 30, bottom: 20, left: 10 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" strokeOpacity={0.5} />
          <XAxis
            dataKey="midpoint"
            type="number"
            domain={[45, 100]}
            ticks={[50, 55, 60, 65, 70, 75, 80, 85, 90, 95]}
            tick={{ fill: '#94a3b8', fontSize: 12 }}
            label={{ value: 'Predicted Confidence (%)', position: 'bottom', offset: 5, style: { fill: '#64748b', fontSize: 12 } }}
            stroke="#475569"
          />
          <YAxis
            dataKey="hitRate"
            type="number"
            domain={[0, 100]}
            ticks={[0, 20, 40, 60, 80, 100]}
            tick={{ fill: '#94a3b8', fontSize: 12 }}
            label={{ value: 'Actual Hit Rate (%)', angle: -90, position: 'insideLeft', offset: 10, style: { fill: '#64748b', fontSize: 12 } }}
            stroke="#475569"
          />
          <Tooltip content={<CustomTooltip />} />

          {/* Perfect calibration diagonal */}
          <ReferenceLine
            segment={[{ x: 45, y: 45 }, { x: 100, y: 100 }]}
            stroke="#64748b"
            strokeDasharray="6 4"
            strokeWidth={1.5}
            label={{ value: 'Perfect', position: 'end', style: { fill: '#64748b', fontSize: 11 } }}
          />

          {/* Confidence band: +/- 10% from diagonal */}
          <Area
            data={[
              { midpoint: 50, upper: 60, lower: 40 },
              { midpoint: 55, upper: 65, lower: 45 },
              { midpoint: 60, upper: 70, lower: 50 },
              { midpoint: 65, upper: 75, lower: 55 },
              { midpoint: 70, upper: 80, lower: 60 },
              { midpoint: 75, upper: 85, lower: 65 },
              { midpoint: 80, upper: 90, lower: 70 },
              { midpoint: 85, upper: 95, lower: 75 },
              { midpoint: 90, upper: 100, lower: 80 },
              { midpoint: 95, upper: 100, lower: 85 },
            ]}
            dataKey="upper"
            stroke="none"
            fill="#3b82f6"
            fillOpacity={0.05}
          />

          {/* Model accuracy line */}
          <Line
            data={chartData}
            type="monotone"
            dataKey="hitRate"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={<CustomDot />}
            isAnimationActive={false}
            connectNulls
          />

          {/* Scatter points (for tooltip targeting) */}
          <Scatter
            data={chartData}
            dataKey="hitRate"
            fill="#3b82f6"
            shape={<CustomDot />}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
