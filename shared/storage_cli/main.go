// Minimal stdin-key launcher for the pinned official 0G Storage CLI.
// The key is added to Go's in-memory os.Args, never the OS process command line.
package main

import (
    "fmt"
    "io"
    "os"
    "regexp"
    "strings"

    "github.com/0gfoundation/0g-storage-client/cmd"
)

const version = "lore-storage-cli/bb5675461a96b654d3015c5522666ee8101cf810"

func main() {
    if len(os.Args) == 2 && os.Args[1] == "--lore-version" {
        fmt.Println(version)
        return
    }
    if len(os.Args) > 1 && os.Args[1] == "upload" {
        raw, err := io.ReadAll(io.LimitReader(os.Stdin, 68))
        key := strings.TrimSpace(string(raw))
        if err != nil || !regexp.MustCompile(`^(0x)?[0-9a-fA-F]{64}$`).MatchString(key) {
            fmt.Fprintln(os.Stderr, "upload requires a 32-byte hex key on stdin")
            os.Exit(2)
        }
        // Never accept a second key through argv.
        for _, arg := range os.Args[2:] {
            if arg == "--key" || strings.HasPrefix(arg, "--key=") {
                fmt.Fprintln(os.Stderr, "argv keys are disabled")
                os.Exit(2)
            }
        }
        os.Args = append(os.Args, "--key", key)
    }
    cmd.Execute()
}
