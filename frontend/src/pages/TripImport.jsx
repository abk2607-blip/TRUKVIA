import React, { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api, API } from "@/api";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Download, Upload, FileSpreadsheet, CheckCircle2, AlertTriangle } from "lucide-react";

export default function TripImport() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef();

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/trips/import", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(data);
      if (data.inserted > 0) {
        toast.success(`Imported ${data.inserted} trip(s)`);
        qc.invalidateQueries();
      } else {
        toast.warning("No rows imported");
      }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="trip-import-page">
      <header className="flex items-center gap-3 border-b border-zinc-200 pb-4">
        <button onClick={() => nav(-1)} className="p-2 border border-zinc-200 rounded-sm"><ArrowLeft size={16} /></button>
        <div>
          <div className="text-[11px] uppercase tracking-[0.15em] text-zinc-500 font-bold">Bulk</div>
          <h1 className="text-3xl font-black tracking-tighter">
            <span className="telugu">ట్రిప్స్ ఇంపోర్ట్</span>
            <span className="text-zinc-400"> · Import Trips</span>
          </h1>
        </div>
      </header>

      <section className="border border-zinc-200 bg-white rounded-sm p-6 space-y-5">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-wider">Step 1 · Template డౌన్‌లోడ్ చేయండి</h3>
          <p className="text-sm text-zinc-600 mt-1">Download the Excel template, fill your trips, and upload it below. Customer names must match your saved customers.</p>
          <a
            data-testid="download-template-btn"
            href={`${API}/trips/import/template`}
            className="mt-3 inline-flex items-center gap-2 px-3 py-2 text-xs uppercase tracking-wider border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white"
          >
            <Download size={14} /> Excel Template
          </a>
        </div>

        <div className="border-t border-zinc-200 pt-5">
          <h3 className="text-sm font-bold uppercase tracking-wider">Step 2 · Upload File</h3>
          <p className="text-sm text-zinc-600 mt-1">Supported: .xlsx or .csv</p>
          <div className="mt-3 flex items-center gap-3">
            <input
              ref={inputRef}
              data-testid="import-file-input"
              type="file"
              accept=".xlsx,.xls,.csv"
              onChange={(e) => { setFile(e.target.files?.[0] || null); setResult(null); }}
              className="text-sm"
            />
            <button
              data-testid="upload-import-btn"
              disabled={!file || busy}
              onClick={upload}
              className="inline-flex items-center gap-2 px-4 py-2 text-xs uppercase tracking-wider bg-zinc-950 text-white rounded-sm hover:bg-zinc-800 disabled:opacity-50"
            >
              <Upload size={14} /> {busy ? "Uploading..." : "Upload & Import"}
            </button>
          </div>
        </div>

        {result && (
          <div className="border-t border-zinc-200 pt-5" data-testid="import-result">
            <h3 className="text-sm font-bold uppercase tracking-wider">Result</h3>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <StatBox icon={FileSpreadsheet} label="Rows" value={result.total_rows} />
              <StatBox icon={CheckCircle2} label="Imported" value={result.inserted} color="text-emerald-700" />
              <StatBox icon={AlertTriangle} label="Errors" value={result.errors.length} color={result.errors.length ? "text-rose-700" : "text-zinc-400"} />
            </div>
            {result.errors.length > 0 && (
              <div className="mt-4 border border-rose-200 rounded-sm">
                <div className="px-4 py-2 bg-rose-50 text-xs font-bold uppercase tracking-wider text-rose-800">Errors</div>
                <table className="w-full text-xs">
                  <thead className="bg-white text-zinc-500">
                    <tr>
                      <th className="text-left px-4 py-1.5 font-semibold">Row</th>
                      <th className="text-left px-4 py-1.5 font-semibold">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.errors.map((e, i) => (
                      <tr key={i} className="border-t border-rose-100">
                        <td className="px-4 py-1.5 font-mono">{e.row}</td>
                        <td className="px-4 py-1.5">{e.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <button
              data-testid="go-to-trips-btn"
              onClick={() => nav("/trips")}
              className="mt-4 px-4 py-2 text-xs uppercase tracking-wider border border-zinc-950 rounded-sm hover:bg-zinc-950 hover:text-white"
            >
              View Trips →
            </button>
          </div>
        )}
      </section>

      <section className="border border-zinc-200 bg-zinc-50 rounded-sm p-5 text-xs text-zinc-600">
        <div className="font-bold uppercase tracking-wider text-zinc-700 mb-2">Column Reference</div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-1 font-mono">
          {["date", "customer_name", "vehicle_number", "driver_name", "load_details", "tons", "from_location", "to_location", "freight_mode (per_ton|fixed)", "rate_per_ton", "fixed_amount", "diesel", "toll", "batta", "repair", "other", "notes"].map((c) => (
            <span key={c} className="px-2 py-0.5 border border-zinc-200 bg-white rounded-sm">{c}</span>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatBox({ icon: Icon, label, value, color = "text-zinc-950" }) {
  return (
    <div className="border border-zinc-200 bg-white p-3 rounded-sm">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500 font-bold">
        <Icon size={12} /> {label}
      </div>
      <div className={`mt-1 font-mono text-2xl font-bold ${color}`}>{value}</div>
    </div>
  );
}
