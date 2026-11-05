import { useState } from 'react'

import { useRunComparisonQuery, useRunsQuery, type RunComparison } from '../api'

type MetricRow = RunComparison['metrics'][number]
type PairedRow = RunComparison['paired'][number]

type Format = 'percent' | 'perDoc' | 'perHundred' | 'grade' | 'chars'

// Plain names and number formats for the metric labels the backend sends
const METRIC_INFO: Record<string, { name: string; format: Format; help: string }> = {
	'concept recall': {
		name: "Doctor's medical concepts kept",
		format: 'percent',
		help: "Share of the medicines, conditions, symptoms, tests and procedures in the doctor's instructions that the summary still mentions. Found by a biomedical language model, not our own word lists.",
	},
	'concept precision': {
		name: 'Medical concepts backed by the record',
		format: 'percent',
		help: 'Share of the medical concepts in the written summary that appear somewhere in the patient record. Fixed warning-sign text and glossary explanations are left out.',
	},
	'SMOG grade': {
		name: 'SMOG grade',
		format: 'grade',
		help: 'Reading grade from words of three or more syllables. Common in health literacy work. Lower is easier.',
	},
	'Dale-Chall score': {
		name: 'Dale-Chall score',
		format: 'grade',
		help: 'Readability from sentence length and words outside a list of 3,000 familiar words. Below 5 is easy for a 4th grader; 7 to 8 is 9th to 10th grade.',
	},
	'difficult words': {
		name: 'Unfamiliar words',
		format: 'percent',
		help: "Share of words outside Dale-Chall's list of familiar words.",
	},
	'unexplained abbreviations': {
		name: 'Unexplained abbreviations per 100 words',
		format: 'perHundred',
		help: 'Distinct abbreviations (like INR or PCP) never explained in parentheses, per 100 words. Target is 0.',
	},
	"doctor's items covered": {
		name: "Doctor's action items kept",
		format: 'percent',
		help: "Share of the doctor's action items (tests, drugs, numbers, appointments) on our own checklist that appear in the summary. The rewrite step checks this same list, so read it alongside concept recall.",
	},
	'unsupported numbers': {
		name: 'Made-up numbers',
		format: 'perDoc',
		help: 'Numbers or dates in the summary that appear nowhere in the chart. Per document; target is 0.',
	},
	'speculative sentences': {
		name: 'Guesses about causes',
		format: 'perDoc',
		help: "Sentences that guess at causes or suggest testing (\"could be\", \"likely due to\"). The doctor's own words don't count.",
	},
	'reading grade': {
		name: 'Reading grade',
		format: 'grade',
		help: 'Flesch-Kincaid school grade of the written sections, medication list excluded. Lower is easier; target is 6.',
	},
	'patient voice': {
		name: 'Talks to the patient as "you"',
		format: 'percent',
		help: 'Share of sentences addressed to the patient.',
	},
	'all 4 sections': {
		name: 'Has all four sections',
		format: 'percent',
		help: 'Share of summaries with what happened, what to do, when to get help, and follow-up.',
	},
	'course conflicts': {
		name: 'Treatment lengths that contradict the record',
		format: 'perDoc',
		help: "A drug's course length in the text that disagrees with the medication list. Per document; target is 0.",
	},
	'restated dosing': {
		name: 'Repeats medicine doses in the text',
		format: 'percent',
		help: 'Share of summaries where the text repeats a dose that the medication list already gives.',
	},
	'repetition loop': {
		name: 'Repetition loops',
		format: 'percent',
		help: 'Share of summaries where the model repeated the same sentences over and over.',
	},
	'filled from the record': {
		name: 'Has sections added from the record',
		format: 'percent',
		help: 'Share of summaries where the doctor left a section empty and it was filled from the chart.',
	},
	'terms explained': {
		name: 'Terms explained',
		format: 'perDoc',
		help: 'Abbreviations and medical words given a plain explanation. Per document.',
	},
	'narrative length': {
		name: 'Length',
		format: 'chars',
		help: 'Characters in the written sections, medication list excluded.',
	},
}

// Shown as tiles, in this order; everything else is in the table
const HEADLINE = ['concept recall', 'concept precision', 'unsupported numbers', 'speculative sentences', 'reading grade', 'unexplained abbreviations']

const infoFor = (label: string) => METRIC_INFO[label] ?? { name: label, format: 'perDoc' as Format, help: '' }

const formatValue = (value: number | null | undefined, format: Format) => {
	if (value === null || value === undefined) return 'Not available'
	switch (format) {
		case 'percent': return `${(value * 100).toFixed(value === 1 || value === 0 ? 0 : 1)}%`
		case 'grade': return value.toFixed(1)
		case 'perHundred': return value.toFixed(2)
		case 'chars': return Math.round(value).toLocaleString('en-US')
		default: return value.toFixed(2)
	}
}

const formatCi = (ci: number[] | null | undefined, format: Format) => {
	if (!ci) return ''
	const plain = (v: number) => (format === 'percent' ? `${(v * 100).toFixed(1)}%` : format === 'chars' ? Math.round(v).toString() : v.toFixed(2))
	return `95% CI ${plain(ci[0])} to ${plain(ci[1])}`
}

const formatDifference = (pair: PairedRow | undefined, format: Format) => {
	if (!pair || pair.difference == null) return 'Not available'
	if (pair.difference === 0 && (!pair.differenceCi || (pair.differenceCi[0] === 0 && pair.differenceCi[1] === 0))) return 'No change'
	const scale = format === 'percent' ? 100 : 1
	const unit = format === 'percent' ? ' pts' : ''
	const signed = (v: number) => `${v >= 0 ? '+' : ''}${(v * scale).toFixed(format === 'chars' ? 0 : 2)}${unit}`
	return pair.differenceCi ? `${signed(pair.difference)} (${signed(pair.differenceCi[0])} to ${signed(pair.differenceCi[1])})` : signed(pair.difference)
}

const formatP = (p: number) => (p < 0.001 ? '< 0.001' : p.toFixed(p < 0.01 ? 3 : 2))

const verdict = (pair: PairedRow | undefined, metric: MetricRow, baseline: string, run: string) => {
	if (!pair) return null
	if (metric.values[baseline] == null && metric.values[run] == null) return 'Not available'
	if (pair.better === 0 && pair.worse === 0) return 'No difference'
	// Wilcoxon uses how big each change was; the sign test only counts direction
	const p = pair.wilcoxonP ?? pair.p
	const direction = pair.better > pair.worse ? 'Better' : pair.worse > pair.better ? 'Worse' : 'Mixed'
	return p < 0.05 ? `${direction} (p ${formatP(p)})` : `No clear difference (p ${formatP(p)})`
}

const MetricTile = ({ metric, run, baseline, pair, clinicianGrade }: {
	metric: MetricRow
	run: string
	baseline: string | null
	pair?: PairedRow
	clinicianGrade?: number | null
}) => {
	const info = infoFor(metric.label)
	return (
		<article className="metric-tile" title={info.help}>
			<h3>{info.name}</h3>
			<p className="metric-tile-value">{formatValue(metric.values[run], info.format)}</p>
			{metric.ci?.[run] && <p className="metric-tile-ci">{formatCi(metric.ci[run], info.format)}</p>}
			{metric.label === 'reading grade' && clinicianGrade != null && (
				<p className="metric-tile-note">Doctors' own instructions: {clinicianGrade.toFixed(1)}</p>
			)}
			{baseline && (
				<p className="metric-tile-note">
					{baseline}: {formatValue(metric.values[baseline], info.format)}
					{pair && <> &middot; {verdict(pair, metric, baseline, run)}</>}
				</p>
			)}
			<p className="metric-tile-help">{info.help}</p>
		</article>
	)
}

const MetricsPanel = () => {
	const runsQuery = useRunsQuery()
	const [picked, setPicked] = useState<string | null>(null)
	const [baseline, setBaseline] = useState<string>('')

	const runs = runsQuery.data?.runs ?? []
	const run = picked ?? runsQuery.data?.defaultRun ?? null
	// the backend tests every run against the first tag
	const tags = run ? (baseline && baseline !== run ? [baseline, run] : [run]) : []
	const comparisonQuery = useRunComparisonQuery(tags)

	if (runsQuery.isPending) return <p>Loading runs...</p>
	if (runsQuery.isError) return <p role="alert">{runsQuery.error.message}</p>
	if (!run) return <p>No summaries have been generated yet, so there is nothing to measure.</p>

	const comparison = comparisonQuery.data
	const activeBaseline = tags.length === 2 ? baseline : null
	const pairFor = (label: string) => comparison?.paired.find((pair) => pair.label === label)
	const metrics = comparison?.metrics ?? []
	const headline = HEADLINE.map((label) => metrics.find((m) => m.label === label)).filter((m): m is MetricRow => Boolean(m))

	return (
		<section className="metrics-page" aria-labelledby="metrics-heading">
			<div className="section-heading metrics-heading">
				<div>
					<h2 id="metrics-heading">Summary Quality</h2>
					<p className="metrics-subtitle">
						Automatic checks on the generated summaries
						{comparison && <> &middot; {comparison.admissions} admissions{activeBaseline ? ' in both runs' : ''}</>}
					</p>
				</div>
				<div className="metrics-controls">
					<label>
						Run
						<select value={run} onChange={(event) => setPicked(event.target.value)}>
							{runs.map((r) => <option key={r.tag} value={r.tag}>{r.tag} ({r.admissions})</option>)}
						</select>
					</label>
					<label>
						Compare with
						<select value={baseline} onChange={(event) => setBaseline(event.target.value)}>
							<option value="">Nothing</option>
							{runs.filter((r) => r.tag !== run).map((r) => <option key={r.tag} value={r.tag}>{r.tag} ({r.admissions})</option>)}
						</select>
					</label>
				</div>
			</div>

			{comparisonQuery.isPending ? <p>Scoring...</p> : comparisonQuery.isError ? <p role="alert">{comparisonQuery.error.message}</p> : comparison && (
				<>
					{comparison.admissions === 0 && <p role="alert">These two runs share no admissions, so they can't be compared.</p>}
					<div className="metric-tiles">
						{headline.map((metric) => (
							<MetricTile key={metric.label} metric={metric} run={run} baseline={activeBaseline}
								pair={pairFor(metric.label)} clinicianGrade={comparison.clinicianGrade} />
						))}
					</div>

					<h3 className="metrics-table-heading">All checks</h3>
					<div className="table-shell">
						<div className="table-scroll">
							<table>
								<thead>
									<tr>
										<th scope="col">Check</th>
										{activeBaseline && <th scope="col">{activeBaseline}</th>}
										<th scope="col">{run}</th>
										{activeBaseline && <th scope="col">Difference (95% CI)</th>}
										{activeBaseline && <th scope="col">Better / worse / tied</th>}
										{activeBaseline && <th scope="col">Result</th>}
									</tr>
								</thead>
								<tbody>
									{metrics.map((metric) => {
										const info = infoFor(metric.label)
										const pair = pairFor(metric.label)
										return (
											<tr key={metric.label}>
												<th scope="row" title={info.help}>{info.name}</th>
												{activeBaseline && (
													<td>
														{formatValue(metric.values[activeBaseline], info.format)}
														{metric.ci?.[activeBaseline] && <span className="metric-cell-ci">{formatCi(metric.ci[activeBaseline], info.format)}</span>}
													</td>
												)}
												<td>
													{formatValue(metric.values[run], info.format)}
													{metric.ci?.[run] && <span className="metric-cell-ci">{formatCi(metric.ci[run], info.format)}</span>}
												</td>
												{activeBaseline && <td>{pair ? formatDifference(pair, info.format) : 'Descriptive only'}</td>}
												{activeBaseline && <td>{pair ? `${pair.better} / ${pair.worse} / ${pair.tied}` : 'Not scored'}</td>}
												{activeBaseline && <td>{pair ? verdict(pair, metric, activeBaseline, run) : 'Descriptive only'}</td>}
											</tr>
										)
									})}
								</tbody>
							</table>
						</div>
					</div>
					<p className="metrics-footnote">
						{activeBaseline
							? `Difference is ${run} minus ${activeBaseline}, with a 95% bootstrap interval. Better / worse counts admissions. p is a Wilcoxon signed-rank test (a sign test where that can't run); below 0.05 is unlikely to be chance.`
							: 'Pick a run to compare with to see which differences are real.'}
						{' '}Concept scores appear after running score-concepts on a run. These are automatic checks, not a clinician's review.
					</p>
				</>
			)}
		</section>
	)
}

export default MetricsPanel
