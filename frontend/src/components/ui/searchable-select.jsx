import * as React from "react";
import { ChevronsUpDown, Check, X as XIcon } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";

/** Iter137A · Reusable searchable combobox.
 *
 *   options: [{ value, label, secondary?, keywords? }]
 *      - value    : opaque id (never rendered as primary label)
 *      - label    : primary display (bold)
 *      - secondary: optional muted line under label (e.g. supplier badge)
 *      - keywords : optional extra strings to match against
 *   value      : currently selected `value` (empty string = no selection)
 *   onChange   : (value) => void
 *   placeholder: input placeholder text
 *   emptyText  : shown when nothing matches
 *   allowClear : show a small clear (×) inside the trigger when a value is set
 *   testId     : root data-testid; individual items expose
 *                `${testId}-option-<value>` and the search input
 *                `${testId}-input`.
 */
export function SearchableSelect({
  options = [],
  value = "",
  onChange,
  placeholder = "Search...",
  emptyText = "No results found",
  allowClear = true,
  disabled = false,
  className,
  testId,
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const selected = React.useMemo(
    () => options.find((o) => o.value === value) || null,
    [options, value],
  );

  const clear = (e) => {
    e.preventDefault();
    e.stopPropagation();
    onChange && onChange("");
  };

  const filtered = React.useMemo(
    () => options.filter((o) => matches(o, query)),
    [options, query],
  );
  const shown = filtered.slice(0, 200);
  const truncated = filtered.length - shown.length;

  return (
    <Popover open={open} onOpenChange={(o) => { setOpen(o); if (!o) setQuery(""); }}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          data-testid={testId}
          className={cn(
            "w-full inline-flex items-center justify-between gap-2 border rounded px-2 py-1 text-sm bg-white text-left",
            "hover:border-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-950 disabled:opacity-50",
            className,
          )}
        >
          <span className={cn("truncate flex-1", !selected && "text-zinc-400")}>
            {selected ? (
              <>
                <span className="font-medium">{selected.label}</span>
                {selected.secondary && (
                  <span className="ml-2 text-xs text-zinc-500">· {selected.secondary}</span>
                )}
              </>
            ) : (
              placeholder
            )}
          </span>
          {allowClear && selected ? (
            <span
              role="button"
              tabIndex={-1}
              onPointerDown={clear}
              onClick={clear}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="p-0 w-[--radix-popover-trigger-width] min-w-[240px]"
      >
        <Command
          shouldFilter={false}
          filter={() => 1}
        >
          <CommandInput
            placeholder={placeholder}
            value={query}
            onValueChange={setQuery}
            data-testid={testId ? `${testId}-input` : undefined}
          />
          <CommandList>
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {shown.map((o) => (
                <CommandItem
                  key={o.value}
                  value={o.value}
                  onSelect={() => {
                    onChange && onChange(o.value);
                    setOpen(false);
                  }}
                  data-testid={testId ? `${testId}-option-${o.value}` : undefined}
                  className="flex items-start gap-2"
                >
                  <Check
                    size={14}
                    className={cn(
                      "mt-0.5 shrink-0",
                      value === o.value ? "opacity-100" : "opacity-0",
                    )}
                  />
                  <div className="flex flex-col min-w-0">
                    <span className="text-sm truncate">{o.label}</span>
                    {o.secondary && (
                      <span className="text-[11px] text-zinc-500 truncate">
                        {o.secondary}
                      </span>
                    )}
                  </div>
                </CommandItem>
              ))}
              {truncated > 0 && (
                <div
                  className="px-3 py-2 text-[11px] text-zinc-500 border-t"
                  data-testid={testId ? `${testId}-truncated` : undefined}
                >
                  Showing first 200 of {filtered.length}. Refine your search…
                </div>
              )}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

function matches(o, q) {
  const needle = (q || "").trim().toLowerCase();
  if (!needle) return true;
  const hay =
    (o.label || "") + " " +
    (o.secondary || "") + " " +
    ((o.keywords || []).join(" "));
  return hay.toLowerCase().includes(needle);
}

export default SearchableSelect;
