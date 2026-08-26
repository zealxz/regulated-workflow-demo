import AppKit
import AVFoundation
import CoreVideo
import Foundation

struct VideoError: Error, CustomStringConvertible {
    let description: String
}

func pixelBuffer(from image: CGImage, width: Int, height: Int) throws -> CVPixelBuffer {
    var buffer: CVPixelBuffer?
    let attributes: [String: Any] = [
        kCVPixelBufferCGImageCompatibilityKey as String: true,
        kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
    ]
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        width,
        height,
        kCVPixelFormatType_32BGRA,
        attributes as CFDictionary,
        &buffer
    )
    guard status == kCVReturnSuccess, let pixelBuffer = buffer else {
        throw VideoError(description: "Could not allocate pixel buffer: \(status)")
    }

    CVPixelBufferLockBaseAddress(pixelBuffer, [])
    defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
    guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
        throw VideoError(description: "Pixel buffer has no base address")
    }
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(
        data: baseAddress,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
    ) else {
        throw VideoError(description: "Could not create bitmap context")
    }
    context.setFillColor(NSColor.white.cgColor)
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    return pixelBuffer
}

func loadImage(_ path: String) throws -> CGImage {
    guard let image = NSImage(contentsOfFile: path) else {
        throw VideoError(description: "Could not load image: \(path)")
    }
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        throw VideoError(description: "Could not decode image: \(path)")
    }
    return cgImage
}

func main() throws {
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard arguments.count >= 3 else {
        throw VideoError(description: "Usage: images_to_mp4.swift OUTPUT.mp4 SECONDS_PER_IMAGE IMAGE.png [...]")
    }
    let outputPath = arguments[0]
    guard let secondsPerImage = Double(arguments[1]), secondsPerImage > 0 else {
        throw VideoError(description: "SECONDS_PER_IMAGE must be positive")
    }
    let imagePaths = Array(arguments.dropFirst(2))
    let width = 1000
    let height = 750
    let fps: Int32 = 30

    let outputURL = URL(fileURLWithPath: outputPath)
    try? FileManager.default.removeItem(at: outputURL)
    try FileManager.default.createDirectory(at: outputURL.deletingLastPathComponent(), withIntermediateDirectories: true)

    let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
    let settings: [String: Any] = [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: width,
        AVVideoHeightKey: height,
        AVVideoCompressionPropertiesKey: [
            AVVideoAverageBitRateKey: 2_200_000,
            AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
        ],
    ]
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
    input.expectsMediaDataInRealTime = false
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(
        assetWriterInput: input,
        sourcePixelBufferAttributes: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height,
        ]
    )
    guard writer.canAdd(input) else {
        throw VideoError(description: "AVAssetWriter rejected the video input")
    }
    writer.add(input)
    guard writer.startWriting() else {
        throw writer.error ?? VideoError(description: "Could not start video writer")
    }
    writer.startSession(atSourceTime: .zero)

    let framesPerImage = Int((secondsPerImage * Double(fps)).rounded())
    var frameIndex: Int64 = 0
    for path in imagePaths {
        let image = try loadImage(path)
        let buffer = try pixelBuffer(from: image, width: width, height: height)
        for _ in 0..<framesPerImage {
            while !input.isReadyForMoreMediaData {
                Thread.sleep(forTimeInterval: 0.002)
            }
            let presentationTime = CMTime(value: frameIndex, timescale: fps)
            guard adaptor.append(buffer, withPresentationTime: presentationTime) else {
                throw writer.error ?? VideoError(description: "Could not append video frame")
            }
            frameIndex += 1
        }
    }

    input.markAsFinished()
    let semaphore = DispatchSemaphore(value: 0)
    writer.finishWriting { semaphore.signal() }
    semaphore.wait()
    guard writer.status == .completed else {
        throw writer.error ?? VideoError(description: "Video writer did not complete")
    }
    print("Created \(outputPath) with \(imagePaths.count) slides and \(frameIndex) frames")
}

do {
    try main()
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
