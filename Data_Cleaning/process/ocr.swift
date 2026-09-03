import Foundation
import Vision
import AppKit

// OCR a directory of PNG pages into Markdown.
// Single-column reading order; tabular regions (consecutive multi-fragment
// rows) are reconstructed as Markdown tables using minX column clustering.
// Usage: ocr.swift <input_dir> <output_file>

struct Fragment {
    let text: String
    let box: CGRect // Vision normalized coords, origin bottom-left
    var minX: CGFloat { box.minX }
    var maxX: CGFloat { box.maxX }
    var midX: CGFloat { box.midX }
    var minY: CGFloat { box.minY }
    var maxY: CGFloat { box.maxY }
    var midY: CGFloat { box.midY }
}

struct Row {
    var fragments: [Fragment] // sorted left-to-right
    var midY: CGFloat
    var text: String { normalize(fragments.map { $0.text }.joined(separator: " ")) }
}

// Fix common OCR misreadings of the Roman numerals Ⅰ/Ⅱ/Ⅲ (recommendation
// levels), which Vision sometimes reads as "I/II/III", "皿", or "|/||/|||".
func normalize(_ s: String) -> String {
    var t = s
    // space-separated variants (pipe-run split from "级" across fragments)
    t = t.replacingOccurrences(of: "||| 级", with: "Ⅲ级")
    t = t.replacingOccurrences(of: "|| 级", with: "Ⅱ级")
    t = t.replacingOccurrences(of: "| 级", with: "Ⅰ级")
    // contiguous variants
    t = t.replacingOccurrences(of: "III级", with: "Ⅲ级")
    t = t.replacingOccurrences(of: "II级", with: "Ⅱ级")
    t = t.replacingOccurrences(of: "I级", with: "Ⅰ级")
    t = t.replacingOccurrences(of: "皿级", with: "Ⅲ级")
    t = t.replacingOccurrences(of: "|||级", with: "Ⅲ级")
    t = t.replacingOccurrences(of: "||级", with: "Ⅱ级")
    t = t.replacingOccurrences(of: "|级", with: "Ⅰ级")
    return t
}

func ocrFragments(cgImage: CGImage) -> [Fragment] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = true
    request.minimumTextHeight = 0.004

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do { try handler.perform([request]) } catch { return [] }
    guard let results = request.results else { return [] }
    return results.compactMap { obs in
        guard let c = obs.topCandidates(1).first else { return nil }
        return Fragment(text: normalize(c.string), box: obs.boundingBox)
    }
}

func groupRows(_ frags: [Fragment]) -> [Row] {
    let sorted = frags.sorted { a, b in
        if abs(a.midY - b.midY) > 0.008 { return a.midY > b.midY }
        return a.minX < b.minX
    }
    var rows: [Row] = []
    for f in sorted {
        if let idx = rows.lastIndex(where: { abs($0.midY - f.midY) <= 0.012 }) {
            rows[idx].fragments.append(f)
            rows[idx].fragments.sort { $0.minX < $1.minX }
            let ys = rows[idx].fragments.map { $0.midY }
            rows[idx].midY = ys.reduce(0, +) / CGFloat(ys.count)
        } else {
            rows.append(Row(fragments: [f], midY: f.midY))
        }
    }
    return rows
}

func isTabular(_ row: Row) -> Bool { row.fragments.count >= 2 }

// Cluster left-edges into column centers. Single-fragment clusters are dropped
// (they are usually merged header cells), EXCEPT those anchored by a header-row
// fragment, which keeps sparsely-populated columns (e.g. Ⅲ级推荐).
func columnCenters(_ block: [Row], tolerance: CGFloat) -> [CGFloat] {
    let xs = block.flatMap { $0.fragments.map { $0.minX } }.sorted()
    guard !xs.isEmpty else { return [] }
    var clusters: [(lo: CGFloat, hi: CGFloat, count: Int)] = []
    var lo = xs[0], hi = xs[0], count = 1
    for x in xs.dropFirst() {
        if x - hi > tolerance {
            clusters.append((lo, hi, count))
            lo = x; hi = x; count = 1
        } else {
            hi = max(hi, x); count += 1
        }
    }
    clusters.append((lo, hi, count))
    let headerXs = block.first?.fragments.map { $0.minX } ?? []
    return clusters.filter { c in
        c.count >= 2 || headerXs.contains { $0 >= c.lo - 0.001 && $0 <= c.hi + 0.001 }
    }.map { ($0.lo + $0.hi) / 2 }
}

func escapeCell(_ s: String) -> String {
    s.replacingOccurrences(of: "|", with: "\\|")
     .replacingOccurrences(of: "\n", with: " ")
     .trimmingCharacters(in: .whitespaces)
}

func assignCells(_ row: Row, centers: [CGFloat]) -> [String] {
    var cells = Array(repeating: "", count: centers.count)
    for f in row.fragments {
        var best = 0, bestD = CGFloat.greatestFiniteMagnitude
        for (i, c) in centers.enumerated() {
            let d = abs(f.minX - c)
            if d < bestD { bestD = d; best = i }
        }
        if !cells[best].isEmpty { cells[best] += " " }
        cells[best] += f.text
    }
    return cells.map { normalize($0) }
}

func emitTable(_ block: [Row], centers: [CGFloat], into out: inout [String]) {
    let ncol = centers.count
    guard ncol >= 2, block.count >= 2 else { return }
    let header = assignCells(block[0], centers: centers).map { escapeCell($0) }
    out.append("| " + header.joined(separator: " | ") + " |")
    out.append("|" + Array(repeating: "---", count: ncol).joined(separator: "|") + "|")
    for row in block.dropFirst() {
        let cells = assignCells(row, centers: centers).map { escapeCell($0) }
        out.append("| " + cells.joined(separator: " | ") + " |")
    }
    out.append("")
}

func processPage(path: String) -> String {
    guard let image = NSImage(contentsOfFile: path),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return "" }

    let allFrags = ocrFragments(cgImage: cg)
    // drop scan watermark / page number: pure digits in the bottom band of the
    // page (measured relative to the lowest content, not the page edge).
    let bottomY = allFrags.map { $0.maxY }.min() ?? 0
    let frags = allFrags.filter {
        let digits = $0.text.allSatisfy { $0.isNumber || $0 == " " }
        return !(digits && $0.maxY < bottomY + 0.05)
    }
    guard !frags.isEmpty else { return "" }
    let rows = groupRows(frags)

    var out: [String] = []
    var i = 0
    while i < rows.count {
        if isTabular(rows[i]) {
            var j = i
            while j < rows.count && isTabular(rows[j]) { j += 1 }
            let block = Array(rows[i..<j])
            if block.count >= 2 {
                let centers = columnCenters(block, tolerance: 0.03)
                if centers.count >= 2 {
                    emitTable(block, centers: centers, into: &out)
                    i = j
                    continue
                }
            }
        }
        out.append(rows[i].text)
        i += 1
    }
    return out.joined(separator: "\n")
}

let args = Array(CommandLine.arguments.dropFirst())
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: ocr.swift <input_dir> <output_file>\n".data(using: .utf8)!)
    exit(1)
}
let dir = args[0]
let outPath = args[1]

let fm = FileManager.default
guard let files = try? fm.contentsOfDirectory(atPath: dir) else { exit(1) }
let pngs = files.filter { $0.hasSuffix(".png") }.sorted()

var output: [String] = []
for f in pngs {
    let path = dir + "/" + f
    let pageNo = String(f.dropFirst(3).prefix(3))
    output.append("<!-- ===== Page \(pageNo) ===== -->")
    output.append("")
    output.append(processPage(path: path))
}

try? output.joined(separator: "\n\n").write(toFile: outPath, atomically: true, encoding: .utf8)
print("wrote \(pngs.count) pages -> \(outPath)")
