import { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
	ArrowLeft,
	ArrowRight,
	Activity,
	CalendarDays,
	ClipboardList,
	FileText,
	HeartPulse,
	Hospital,
	MapPin,
	UserRound,
} from 'lucide-react'

import { useEncounterQuery, useGenerateDocumentMutation, usePatientQuery, type Encounter } from './api'
import DashboardHeader from './components/DashboardHeader'
import DashboardSidebar, { type NavigationItem } from './components/DashboardSidebar'
import HealthTables from './components/HealthTables'

const formatDate = (value: string | null | undefined) => {
	if (value) {
		return new Intl.DateTimeFormat('en-US', { dateStyle: 'long' }).format(new Date(value))
	}

	return 'Date not recorded'
}

type GlossaryStyle = 'separate' | 'inline'

// with the separate style, an item's first line is the instruction and each later line explains a word
const ItemText = ({ text }: { text: string }) => {
	const [first, ...explanations] = text.split('\n')
	return (
		<>
			{first}
			{explanations.map((line) => <span className="item-explanation" key={line}>{line}</span>)}
		</>
	)
}

const InstructionSections = ({ encounter }: { encounter: Encounter }) => (
	<>
		{(encounter.sections ?? []).map((section) => (
			<div key={section.header}>
				<h4>{section.header}:</h4>
				{section.from_record && <p className="section-source">Your care team did not write this part, so it was added from your hospital record.</p>}
				<ul className="discharge-instructions">
					{section.items.map((item, index) => <li key={`${section.header}-${index}`}><ItemText text={item} /></li>)}
				</ul>
			</div>
		))}
	</>
)

const MedicationChangesCard = ({ encounter }: { encounter: Encounter }) => {
	const changes = encounter.medication_changes
	if (!changes?.available) return null
	const { new: started = [], stopped = [], changed = [] } = changes
	const none = started.length + stopped.length + changed.length === 0
	return (
		<section className="med-changes" aria-labelledby="med-changes-heading">
			<h4 id="med-changes-heading">Changes to your medicines:</h4>
			{none && <p>Keep taking the medicines you took before you came to the hospital. Nothing changed.</p>}
			{started.length > 0 && (
				<div className="med-change-group">
					<p className="med-change-label">START taking</p>
					<ul>{started.map((c) => <li key={`new-${c.name}`}>{c.now}</li>)}</ul>
				</div>
			)}
			{stopped.length > 0 && (
				<div className="med-change-group">
					<p className="med-change-label">STOP taking</p>
					<ul>{stopped.map((c) => <li key={`stop-${c.name}`}>{c.before}</li>)}</ul>
				</div>
			)}
			{changed.length > 0 && (
				<div className="med-change-group">
					<p className="med-change-label">CHANGED: take it the new way</p>
					<ul>
						{changed.map((c) => (
							<li key={`change-${c.name}`}>
								<span className="med-change-before">Before: {c.before}</span>
								<span>Now: {c.now}</span>
							</li>
						))}
					</ul>
				</div>
			)}
			{changes.admission_list_incomplete && (
				<p className="section-source">The list of medicines you took before the hospital may not be complete. Check it with your care team.</p>
			)}
		</section>
	)
}

const MedicationList = ({ encounter }: { encounter: Encounter }) => {
	const details = encounter.medication_details ?? []
	return (
		<>
			<MedicationChangesCard encounter={encounter} />
			<h4>Your medicines:</h4>
			{details.length > 0 ? (
				<ul className="discharge-instructions med-list">
					{details.map((medication, index) => (
						<li key={`med-${index}`}>
							<span className="med-text">{medication.text}</span>
							{medication.purpose && <span className="med-purpose">What it's for: {medication.purpose}</span>}
							{medication.for_condition && <span className="med-purpose">{medication.for_condition}</span>}
						</li>
					))}
				</ul>
			) : <p>No medicines were listed.</p>}
			<h4>Allergies:</h4>
			<p>{(encounter.allergies ?? []).length > 0 ? (encounter.allergies ?? []).join(', ') : 'No known allergies.'}</p>
		</>
	)
}

const GenerateButton = ({ encounter }: { encounter: Encounter }) => {
	const generate = useGenerateDocumentMutation()
	return (
		<div className="generate-panel">
			<p>No accessible summary has been generated for this visit yet.</p>
			<button className="generate-button" type="button" disabled={generate.isPending} onClick={() => generate.mutate(Number(encounter.id))}>
				{generate.isPending ? 'Generating... this can take a minute' : 'Generate accessible summary'}
			</button>
			{generate.isError && <p role="alert">{generate.error.message}</p>}
		</div>
	)
}

const AtAGlance = ({ encounter }: { encounter: Encounter }) => (
	<aside className="summary-at-a-glance" aria-labelledby="glance-heading">
		<h3 id="glance-heading">Visit At-A-Glance</h3>
		<p><strong>Service:</strong> {encounter.service ?? 'Not recorded'}</p>
		<p><strong>Date admitted:</strong> {formatDate(encounter.admission_date)}</p>
		<p><strong>Date discharged:</strong> {formatDate(encounter.discharge_date)}</p>
		<p><strong>Reason:</strong> {encounter.reason ?? 'Not recorded'}</p>
		<p><strong>Provider:</strong> {encounter.provider ?? 'Not recorded'}</p>
		<p><strong>Location:</strong> {encounter.location ?? 'Not recorded'}</p>
	</aside>
)

const AccessibleSummary = ({ encounter }: { encounter: Encounter }) => (
	<div className="encounter-summary-grid">
		<section className="summary-copy" aria-labelledby="summary-heading">
			<h3 id="summary-heading">Accessible Visit Summary</h3>
			{encounter.document_id == null ? <GenerateButton encounter={encounter} /> : (
				<>
					<h4>What happened in the hospital:</h4>
					<p>{encounter.summary ? <ItemText text={encounter.summary} /> : 'No summary was written for this visit.'}</p>
					<InstructionSections encounter={encounter} />
					<MedicationList encounter={encounter} />
				</>
			)}
		</section>
		<AtAGlance encounter={encounter} />
	</div>
)

const OriginalSummary = ({ encounter }: { encounter: Encounter }) => (
	<div className="encounter-summary-grid">
		<section className="summary-copy" aria-labelledby="original-heading">
			<h3 id="original-heading">Original Visit Summary</h3>
			<h4>Instructions written by your care team:</h4>
			{encounter.original_summary
				? encounter.original_summary.split('\n\n').map((paragraph, index) => <p className="original-paragraph" key={`para-${index}`}>{paragraph}</p>)
				: <p>No instructions were written for this visit.</p>}
		</section>
		<AtAGlance encounter={encounter} />
	</div>
)

const InstructionsContent = ({ encounter }: { encounter: Encounter }) => (
	<section className="instructions-only summary-copy" aria-labelledby="instructions-heading">
		<h3 id="instructions-heading">Discharge Instructions</h3>
		<MedicationChangesCard encounter={encounter} />
		{encounter.document_id == null ? <GenerateButton encounter={encounter} /> : <InstructionSections encounter={encounter} />}
	</section>
)

type ClinicalNote = Encounter['notes'][number]

const ClinicalNote = ({ note }: { note: ClinicalNote }) => (
	<article className="clinical-note">
		<h3>{note.title}</h3>
		<pre className="clinical-note-content">{note.content}</pre>
	</article>
)

type EncounterDetailProps = {
	encounter: Encounter
	onBack: () => void
	glossaryStyle: GlossaryStyle
	onGlossaryStyle: (style: GlossaryStyle) => void
}

const EncounterDetail = ({ encounter, onBack, glossaryStyle, onGlossaryStyle }: EncounterDetailProps) => {
	// 3 display buttons to swap encounter view
	const [documentView, setDocumentView] = useState<'original' | 'accessible' | 'instructions'>('accessible')
	const [section, setSection] = useState<'summary' | 'notes'>('summary')

	const notes = encounter.notes.length > 0
		? encounter.notes
		: [{ id: 'summary', title: 'Encounter summary', content: encounter.summary ?? 'No clinical notes are available.' }]

	return (
		<div className="encounter-detail">
			<button className="encounter-back-button" type="button" onClick={onBack}>
				<ArrowLeft size={17} aria-hidden="true" /> All Encounters
			</button>
			<header className="encounter-header">
				<div>
					<h1>{encounter.reason ?? 'Encounter'}</h1>
					<div className="encounter-meta">
						<span><UserRound size={16} aria-hidden="true" /> {encounter.provider ?? encounter.service ?? 'Provider not recorded'}</span>
						<span><MapPin size={16} aria-hidden="true" /> {encounter.location ?? 'Location not recorded'}</span>
					</div>
				</div>
				<div className="encounter-date"><CalendarDays size={17} aria-hidden="true" /> {formatDate(encounter.admission_date)}</div>
			</header>
			<div className="encounter-tabs" role="tablist" aria-label="Encounter documents">
				<button className={section === 'summary' ? 'is-active' : ''} type="button" role="tab" aria-selected={section === 'summary'} onClick={() => setSection('summary')}>
					<ClipboardList size={17} aria-hidden="true" /> Discharge Summary
				</button>
				<button className={section === 'notes' ? 'is-active' : ''} type="button" role="tab" aria-selected={section === 'notes'} onClick={() => setSection('notes')}>
					<FileText size={17} aria-hidden="true" /> Clinical Notes
				</button>
			</div>
			{section === 'summary' ? (
				<>
					<div className="document-toolbar">
						<strong><Activity size={18} aria-hidden="true" /> Toggle document</strong>
						<div role="group" aria-label="Document view">
							<button className={documentView === 'original' ? 'is-active' : ''} type="button" onClick={() => setDocumentView('original')}>Original Summary</button>
							<button className={documentView === 'accessible' ? 'is-active' : ''} type="button" onClick={() => setDocumentView('accessible')}>Accessible Summary</button>
							<button className={documentView === 'instructions' ? 'is-active' : ''} type="button" onClick={() => setDocumentView('instructions')}>Instructions Only</button>
						</div>
						{/* both styles stay available until user testing picks one */}
						<div role="group" aria-label="How medical words are explained">
							<button className={glossaryStyle === 'separate' ? 'is-active' : ''} type="button" onClick={() => onGlossaryStyle('separate')}>Explanations below</button>
							<button className={glossaryStyle === 'inline' ? 'is-active' : ''} type="button" onClick={() => onGlossaryStyle('inline')}>Explanations in text</button>
						</div>
					</div>
					<div className="document-card">
						{documentView === 'instructions' ? <InstructionsContent encounter={encounter} />
							: documentView === 'original' ? <OriginalSummary encounter={encounter} />
							: <AccessibleSummary encounter={encounter} />}
					</div>
				</>
			) : (
				<div className="clinical-notes-card">
					<h2>Clinical Notes</h2>
					{notes.map((note) => <ClinicalNote key={note.id} note={note} />)}
				</div>
			)}
		</div>
	)
}

const PatientDashboard = () => {
	// Get patientId from URL
	// TODO: can maybe swap with some sort of login if we want
	const { patientId = '' } = useParams()
	const patientQuery = usePatientQuery(patientId)

	const [selectedEncounterId, setSelectedEncounterId] = useState<string | null>(null)
	const [selectedPage, setSelectedPage] = useState<'Encounters' | 'Health'>('Encounters')
	const [glossaryStyle, setGlossaryStyle] = useState<GlossaryStyle>('separate')
	const encounterQuery = useEncounterQuery(patientId, selectedEncounterId ?? '', glossaryStyle)

	const navigationItems: NavigationItem[] = [
		{ label: 'Encounters', icon: Hospital },
		{ label: 'Health', icon: HeartPulse },
	]

	if (patientQuery.isPending) return <main className="dashboard-content">Loading patient...</main>
	if (patientQuery.isError) return <main className="dashboard-content"><p role="alert">{patientQuery.error.message}</p></main>

	const patient = patientQuery.data
	const selectedEncounter = encounterQuery.data


	return (
		<div className="dashboard-shell">
			<DashboardHeader />
			<DashboardSidebar
				items={navigationItems}
				pageName="Patient Dashboard"
				activeItem={selectedPage}
				onSelect={(label) => {
					if (label === 'Encounters' || label === 'Health') {
						setSelectedPage(label)
						if (label === 'Health') {
							setSelectedEncounterId(null)
						}
					}
				}}
			/>
			<main className="dashboard-main">
				<div className="dashboard-content">
					{selectedPage === 'Health' ? <HealthTables patientId={patientId} /> : selectedEncounterId ? (
						encounterQuery.isPending ? <p>Loading encounter...</p> : encounterQuery.isError ? <p role="alert">{encounterQuery.error.message}</p> : selectedEncounter ? (
							<EncounterDetail
								encounter={selectedEncounter}
								onBack={() => setSelectedEncounterId(null)}
								glossaryStyle={glossaryStyle}
								onGlossaryStyle={setGlossaryStyle}
							/>
						) : null
					) : (
						<section className="encounters-page" aria-labelledby="encounters-heading">
							<div className="section-heading">
								<div>
									<h1 id="encounters-heading">{patient.name}</h1>
								</div>
							</div>
							<div className="encounter-list">
								{patient.encounters.length === 0 ? <p>No encounters are available.</p> : patient.encounters.map((encounter) => (
									<button className="encounter-list-item" key={encounter.id} type="button" onClick={() => setSelectedEncounterId(encounter.id)}>
										<span className="encounter-list-icon"><Hospital size={20} aria-hidden="true" /></span>
										<span className="encounter-list-info">
											<strong>{encounter.reason ?? 'Encounter'}</strong>
											<span>{encounter.summary ?? 'No summary recorded'}</span>
											<small>{encounter.service ?? 'Service not recorded'}</small>
										</span>
										<span className="encounter-list-date">{formatDate(encounter.admission_date)}</span>
										<ArrowRight className="encounter-list-arrow" size={18} aria-hidden="true" />
									</button>
								))}
							</div>
						</section>
					)}
				</div>
			</main>
		</div>
	)
}

export default PatientDashboard
