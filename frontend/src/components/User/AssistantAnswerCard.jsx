import { BarChart, Bar, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

/**
 * Kartu jawaban asisten: paragraf ringkasan + tabel data kecil +
 * (opsional) satu chart batang Recharts.
 * Renderer generik — bentuk data dikirim oleh services/mockChat.js (MOCK),
 * jadi saat Fase 3 komponen ini tidak perlu berubah.
 */
export default function AssistantAnswerCard({ answer }) {
  return (
    <div className="bg-white border border-hairline rounded-xl rounded-tl-md shadow-sm p-4 space-y-3">
      <p className="text-body text-sm leading-relaxed">{answer.summary}</p>

      {answer.table && (
        <div>
          {answer.table.title && (
            <p className="text-xs font-medium text-ink mb-1.5">{answer.table.title}</p>
          )}
          <div className="border border-hairline rounded-lg overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-soft text-xs text-muted">
                <tr>
                  {answer.table.columns.map((col) => (
                    <th key={col} className="px-3 py-2 font-medium">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {answer.table.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-surface-soft/50 transition-colors">
                    {row.map((cell, j) => (
                      <td key={j} className={`px-3 py-2 ${j === 0 ? 'text-ink font-medium' : 'text-body'}`}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {answer.chart && (
        <div>
          <p className="text-xs font-medium text-ink mb-1">{answer.chart.title}</p>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={answer.chart.data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-hairline)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: 'var(--color-muted)' }}
                  stroke="var(--color-hairline)"
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: 'var(--color-muted)' }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  cursor={{ fill: 'var(--color-surface-soft)', fillOpacity: 0.6 }}
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    border: '1px solid var(--color-hairline)',
                  }}
                  formatter={(value) => [`${value} ${answer.chart.unit}`, answer.chart.title]}
                />
                <Bar dataKey="value" fill="var(--color-primary)" radius={[4, 4, 0, 0]} maxBarSize={48} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <p className="text-[11px] text-muted">
        Sumber: {answer.source}
        {answer.createdAt &&
          ` · ${new Date(answer.createdAt).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}`}
      </p>
    </div>
  );
}
