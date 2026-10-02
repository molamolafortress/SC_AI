// Tiny 32-bit Windows loader check for a BWAPI module DLL: LoadLibrary + the two exports.
// Build: body/mcrave_port/build_win.sh builds it alongside McRave.dll; run: wine build/mcrave_win/loadtest.exe build/mcrave_win/McRave.dll
#include <windows.h>
#include <cstdio>
int main(int argc, char** argv) {
    if (argc < 2) { std::printf("usage: loadtest <module.dll>\n"); return 2; }
    HMODULE h = LoadLibraryA(argv[1]);
    if (!h) { std::printf("LoadLibrary failed: %lu\n", GetLastError()); return 1; }
    void* a = (void*)GetProcAddress(h, "gameInit");
    void* b = (void*)GetProcAddress(h, "newAIModule");
    std::printf("loaded %s gameInit=%p newAIModule=%p\n", argv[1], a, b);
    return (a && b) ? 0 : 1;
}
