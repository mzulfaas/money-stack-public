import Vision
import Cocoa

guard CommandLine.arguments.count > 1 else {
    fputs("Usage: ocr_screen <image-path> [--find <query>] [--json]\n", stderr)
    exit(1)
}

let path = CommandLine.arguments[1]
var findQuery: String? = nil
var outputJson = false

var i = 2
while i < CommandLine.arguments.count {
    let arg = CommandLine.arguments[i]
    if arg == "--find" && i + 1 < CommandLine.arguments.count {
        findQuery = CommandLine.arguments[i + 1]
        i += 2
    } else if arg == "--json" {
        outputJson = true
        i += 1
    } else {
        i += 1
    }
}

let url = URL(fileURLWithPath: path)
guard let image = NSImage(contentsOf: url),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("Error: Could not load image at \(path)\n", stderr)
    exit(2)
}

let imgW = Double(cgImage.width)
let imgH = Double(cgImage.height)

struct TextResult: Codable {
    let text: String
    let confidence: Float
    let x: Int
    let y: Int
    let w: Int
    let h: Int
    let center_x: Int
    let center_y: Int
}

var results: [TextResult] = []

let request = VNRecognizeTextRequest { req, _ in
    guard let observations = req.results as? [VNRecognizedTextObservation] else { return }
    for obs in observations {
        guard let cand = obs.topCandidates(1).first else { continue }
        let box = obs.boundingBox
        let x = Int(box.origin.x * imgW)
        let y = Int((1.0 - box.origin.y - box.size.height) * imgH)
        let w = Int(box.size.width * imgW)
        let h = Int(box.size.height * imgH)
        let cx = x + w / 2
        let cy = y + h / 2
        results.append(TextResult(
            text: cand.string,
            confidence: cand.confidence,
            x: x, y: y, w: w, h: h,
            center_x: cx, center_y: cy
        ))
    }
}

request.recognitionLevel = .accurate
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try? handler.perform([request])

if outputJson {
    let encoder = JSONEncoder()
    encoder.outputFormatting = .prettyPrinted
    if let data = try? encoder.encode(results), let jsonStr = String(data: data, encoding: .utf8) {
        print(jsonStr)
    }
} else if let query = findQuery {
    for r in results {
        if r.text.localizedCaseInsensitiveContains(query) {
            print("MATCH: [\(r.text)] center=(\(r.center_x), \(r.center_y)) bounds=[\(r.x), \(r.y), \(r.w), \(r.h)]")
        }
    }
} else {
    for r in results {
        print(r.text)
    }
}
