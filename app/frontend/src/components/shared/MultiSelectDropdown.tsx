import { useState, useRef, useEffect, useCallback } from 'react';

interface Props {
  label: string;
  options: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
  searchPlaceholder?: string;
  onSearchChange?: (q: string) => void;
}

export function MultiSelectDropdown({ label, options, selected, onChange, searchPlaceholder, onSearchChange }: Props) {
  const [open, setOpen] = useState(false);
  const [searchQ, setSearchQ] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const toggle = useCallback((name: string) => {
    onChange(selected.includes(name) ? selected.filter(s => s !== name) : [...selected, name]);
  }, [selected, onChange]);

  const handleSearch = (q: string) => {
    setSearchQ(q);
    onSearchChange?.(q);
  };

  const handleOpen = () => {
    setOpen(o => !o);
    if (!open) {
      setSearchQ('');
      onSearchChange?.('');
    }
  };

  return (
    <div className="multiselect-dropdown" ref={containerRef}>
      <button
        className={`multiselect-trigger all-search-filter-input${selected.length > 0 ? ' multiselect-trigger-active' : ''}`}
        onClick={handleOpen}
        type="button"
      >
        {selected.length === 0
          ? label
          : selected.length === 1
          ? selected[0]
          : `${label} (${selected.length})`}
        <span className="multiselect-chevron" />
      </button>

      {open && (
        <div className="multiselect-popover">
          {(onSearchChange || options.length > 8) && (
            <input
              autoFocus
              type="search"
              className="multiselect-search"
              placeholder={searchPlaceholder ?? `Search ${label.toLowerCase()}...`}
              value={searchQ}
              onChange={e => handleSearch(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }}
            />
          )}
          {selected.length > 0 && (
            <button className="multiselect-clear" onClick={() => onChange([])}>
              Clear all
            </button>
          )}
          <div className="multiselect-options">
            {options.length === 0
              ? <span className="multiselect-empty">No results</span>
              : options.map(name => (
                <label key={name} className="multiselect-option">
                  <input
                    type="checkbox"
                    checked={selected.includes(name)}
                    onChange={() => toggle(name)}
                  />
                  <span>{name}</span>
                </label>
              ))
            }
          </div>
        </div>
      )}

    </div>
  );
}
