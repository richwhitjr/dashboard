import { useRef, useState } from 'react';
import {
  usePersonas,
  useCreatePersona,
  useUpdatePersona,
  useDeletePersona,
  useUploadPersonaAvatar,
} from '../api/hooks';
import type { Persona } from '../api/types';

const EMPTY_FORM = { name: '', description: '', system_prompt: '' };

function PersonaAvatar({ persona, size = 40 }: { persona: Persona; size?: number }) {
  if (persona.avatar_filename) {
    return (
      <img
        src={`/api/personas/${persona.id}/avatar`}
        alt={persona.name}
        className="persona-avatar"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div
      className="persona-avatar-placeholder"
      style={{ width: size, height: size, fontSize: size * 0.45 }}
    >
      {persona.name.charAt(0).toUpperCase()}
    </div>
  );
}

function AvatarUpload({ persona }: { persona: Persona }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const upload = useUploadPersonaAvatar();

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    upload.mutate({ id: persona.id, file });
    e.target.value = '';
  }

  return (
    <div
      className="persona-avatar-upload"
      onClick={() => fileRef.current?.click()}
      title="Click to upload avatar"
    >
      <PersonaAvatar persona={persona} size={48} />
      <div className="persona-avatar-upload-overlay">
        {upload.isPending ? '...' : 'Edit'}
      </div>
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        onChange={handleFileChange}
        style={{ display: 'none' }}
      />
    </div>
  );
}

export function PersonasPage() {
  const { data: personas, isLoading } = usePersonas();
  const createPersona = useCreatePersona();
  const updatePersona = useUpdatePersona();
  const deletePersona = useDeletePersona();

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!createForm.name.trim()) return;
    createPersona.mutate(createForm, {
      onSuccess: () => {
        setCreateForm(EMPTY_FORM);
        setShowCreate(false);
      },
    });
  }

  function startEdit(persona: Persona) {
    setEditingId(persona.id);
    setEditForm({
      name: persona.name,
      description: persona.description,
      system_prompt: persona.system_prompt,
    });
  }

  function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (editingId === null) return;
    updatePersona.mutate({ id: editingId, ...editForm }, {
      onSuccess: () => setEditingId(null),
    });
  }

  function handleDelete(id: number) {
    deletePersona.mutate(id);
  }

  if (isLoading) return <p>Loading...</p>;

  return (
    <article>
      <h1>Personas</h1>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)', marginBottom: 'var(--space-lg)' }}>
        Customize Claude's behavior with specialized system prompts. Select a persona when opening a new Claude tab.
      </p>

      <button
        className="auth-action-btn"
        onClick={() => setShowCreate(!showCreate)}
        style={{ marginBottom: 'var(--space-lg)' }}
      >
        {showCreate ? 'Cancel' : 'Create Persona'}
      </button>

      {showCreate && (
        <form onSubmit={handleCreate} className="persona-form" style={{ marginBottom: 'var(--space-xl)' }}>
          <div className="persona-card">
            <input
              type="text"
              placeholder="Name"
              value={createForm.name}
              onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
              style={{ width: '100%', marginBottom: 'var(--space-sm)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-xs) var(--space-sm)' }}
              required
            />
            <input
              type="text"
              placeholder="Short description"
              value={createForm.description}
              onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
              style={{ width: '100%', marginBottom: 'var(--space-sm)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-xs) var(--space-sm)' }}
            />
            <textarea
              placeholder="System prompt — instructions that shape Claude's behavior..."
              value={createForm.system_prompt}
              onChange={(e) => setCreateForm({ ...createForm, system_prompt: e.target.value })}
              style={{ width: '100%', minHeight: 120, fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-sm)', resize: 'vertical' }}
            />
            <div style={{ marginTop: 'var(--space-sm)', color: 'var(--color-text-light)', fontSize: 'var(--text-xs)' }}>
              You can upload an avatar image after creating the persona.
            </div>
            <div style={{ marginTop: 'var(--space-sm)' }}>
              <button type="submit" className="auth-action-btn" disabled={createPersona.isPending}>
                {createPersona.isPending ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </form>
      )}

      <div>
        {personas?.map((persona) => (
          <div key={persona.id} className="persona-card">
            {editingId === persona.id ? (
              <form onSubmit={handleUpdate} className="persona-form">
                <div style={{ display: 'flex', gap: 'var(--space-md)', marginBottom: 'var(--space-sm)' }}>
                  <AvatarUpload persona={persona} />
                  <div style={{ flex: 1 }}>
                    <input
                      type="text"
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      style={{ width: '100%', marginBottom: 'var(--space-sm)', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-xs) var(--space-sm)' }}
                      required
                    />
                    <input
                      type="text"
                      value={editForm.description}
                      onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                      style={{ width: '100%', fontFamily: 'var(--font-body)', fontSize: 'var(--text-sm)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-xs) var(--space-sm)' }}
                    />
                  </div>
                </div>
                <textarea
                  value={editForm.system_prompt}
                  onChange={(e) => setEditForm({ ...editForm, system_prompt: e.target.value })}
                  style={{ width: '100%', minHeight: 120, fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', border: '1px solid var(--color-border)', borderRadius: 4, padding: 'var(--space-sm)', resize: 'vertical' }}
                />
                <div style={{ marginTop: 'var(--space-sm)', display: 'flex', gap: 'var(--space-sm)' }}>
                  <button type="submit" className="auth-action-btn" disabled={updatePersona.isPending}>
                    {updatePersona.isPending ? 'Saving...' : 'Save'}
                  </button>
                  <button type="button" className="auth-action-btn" onClick={() => setEditingId(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <>
                <div className="persona-card-header">
                  <AvatarUpload persona={persona} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600 }}>{persona.name}</div>
                    {persona.description && (
                      <div style={{ color: 'var(--color-text-muted)', fontSize: 'var(--text-sm)' }}>
                        {persona.description}
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--space-xs)' }}>
                    <button
                      className="auth-action-btn"
                      onClick={() => startEdit(persona)}
                      style={{ fontSize: 'var(--text-xs)' }}
                    >
                      Edit
                    </button>
                    {!persona.is_default && (
                      <button
                        className="auth-action-btn"
                        onClick={() => handleDelete(persona.id)}
                        disabled={deletePersona.isPending}
                        style={{ fontSize: 'var(--text-xs)', color: 'var(--color-accent)' }}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
                {persona.system_prompt && (
                  <div className="persona-prompt-preview">
                    {persona.system_prompt}
                  </div>
                )}
                {persona.is_default && !persona.system_prompt && (
                  <div style={{ color: 'var(--color-text-light)', fontSize: 'var(--text-xs)', fontStyle: 'italic' }}>
                    Uses the standard dashboard system prompt
                  </div>
                )}
              </>
            )}
          </div>
        ))}
      </div>
    </article>
  );
}
