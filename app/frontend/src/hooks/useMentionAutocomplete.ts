import { useState, useRef, useCallback, useMemo } from 'react';
import type { Employee } from '../api/types';

export function useMentionAutocomplete(employees: Employee[] | undefined) {
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStart, setMentionStart] = useState(-1);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(
    () =>
      mentionQuery !== null && employees
        ? employees.filter((e) =>
            mentionQuery === '' ||
            e.name.toLowerCase().includes(mentionQuery.toLowerCase()) ||
            e.name.toLowerCase().split(' ')[0].startsWith(mentionQuery.toLowerCase())
          )
        : [],
    [mentionQuery, employees],
  );

  const isOpen = mentionQuery !== null && matches.length > 0;

  const handleChange = useCallback((text: string) => {
    const input = inputRef.current;
    if (!input) return;
    const cursor = input.selectionStart ?? text.length;

    const before = text.slice(0, cursor);
    const atIndex = before.lastIndexOf('@');

    if (atIndex >= 0 && (atIndex === 0 || before[atIndex - 1] === ' ')) {
      const query = before.slice(atIndex + 1);
      if (!query.includes(' ') || query.length <= 20) {
        setMentionQuery(query);
        setMentionStart(atIndex);
        setSelectedIndex(0);
        return;
      }
    }
    setMentionQuery(null);
    setMentionStart(-1);
  }, []);

  const dismiss = useCallback(() => {
    setMentionQuery(null);
    setMentionStart(-1);
  }, []);

  const selectEmployee = useCallback((text: string, emp: Employee): string => {
    const firstName = emp.name.split(' ')[0];
    const before = text.slice(0, mentionStart);
    const cursor = inputRef.current?.selectionStart ?? text.length;
    const after = text.slice(cursor);
    const newText = `${before}@${firstName} ${after}`;
    dismiss();
    return newText;
  }, [mentionStart, dismiss]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent, text: string, setText: (s: string) => void) => {
    if (!isOpen) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, matches.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Tab' || (e.key === 'Enter' && matches.length > 0)) {
      e.preventDefault();
      const emp = matches[selectedIndex];
      if (emp) {
        setText(selectEmployee(text, emp));
      }
    } else if (e.key === 'Escape') {
      dismiss();
    }
  }, [isOpen, matches, selectedIndex, selectEmployee, dismiss]);

  return {
    inputRef,
    matches,
    isOpen,
    selectedIndex,
    handleChange,
    handleKeyDown,
    selectEmployee,
    dismiss,
  };
}
