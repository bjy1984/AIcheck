import Foundation
import Vision
import ImageIO
import CoreGraphics

struct OCRLine: Codable {
    let text: String
    let confidence: Float
    let boundingBox: [Double]
}

struct OCRResult: Codable {
    let path: String
    let text: String
    let observations: [OCRLine]
    let error: String?
}

func imageOrientation(from source: CGImageSource) -> CGImagePropertyOrientation {
    guard
        let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
        let rawValue = properties[kCGImagePropertyOrientation] as? UInt32,
        let orientation = CGImagePropertyOrientation(rawValue: rawValue)
    else {
        return .up
    }
    return orientation
}

func recognize(path: String) -> OCRResult {
    let url = URL(fileURLWithPath: path)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else {
        return OCRResult(path: path, text: "", observations: [], error: "cannot_open_image")
    }

    let options = [kCGImageSourceShouldCache: true] as CFDictionary
    guard let image = CGImageSourceCreateImageAtIndex(source, 0, options) else {
        return OCRResult(path: path, text: "", observations: [], error: "cannot_decode_image")
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]

    let handler = VNImageRequestHandler(
        cgImage: image,
        orientation: imageOrientation(from: source),
        options: [:]
    )

    do {
        try handler.perform([request])
    } catch {
        return OCRResult(path: path, text: "", observations: [], error: String(describing: error))
    }

    let recognized = request.results?.sorted { lhs, rhs in
        let dy = abs(lhs.boundingBox.midY - rhs.boundingBox.midY)
        if dy > 0.02 {
            return lhs.boundingBox.midY > rhs.boundingBox.midY
        }
        return lhs.boundingBox.minX < rhs.boundingBox.minX
    } ?? []

    let lines: [OCRLine] = recognized.compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else {
            return nil
        }
        let box = observation.boundingBox
        return OCRLine(
            text: candidate.string,
            confidence: candidate.confidence,
            boundingBox: [
                Double(box.minX),
                Double(box.minY),
                Double(box.width),
                Double(box.height)
            ]
        )
    }

    return OCRResult(
        path: path,
        text: lines.map { $0.text }.joined(separator: "\n"),
        observations: lines,
        error: nil
    )
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.withoutEscapingSlashes]

for path in CommandLine.arguments.dropFirst() {
    let result = recognize(path: path)
    if let data = try? encoder.encode(result), let json = String(data: data, encoding: .utf8) {
        print(json)
    }
}
