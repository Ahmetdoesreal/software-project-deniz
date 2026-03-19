import Foundation
import AppKit

print("Starting Student Companion Native Wrapper...")

// Get the path to the Python script in the bundle
if let resourcePath = Bundle.main.resourcePath {
    let scriptPath = (resourcePath as NSString).appendingPathComponent("companion.py")
    
    let process = Process()
    // Using /usr/bin/env to find python3 in the user's path, or you can specify a full path
    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    process.arguments = ["python3", scriptPath]
    
    // Set current directory to the project root if needed
    // process.currentDirectoryURL = ...
    
    do {
        try process.run()
        process.waitUntilExit()
        exit(process.terminationStatus)
    } catch {
        print("Failed to run python script: \(error)")
        exit(1)
    }
} else {
    print("Could not find Resource path")
    exit(1)
}
