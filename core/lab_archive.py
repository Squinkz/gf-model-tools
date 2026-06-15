from dataclasses import dataclass
from pathlib import Path
import struct


SUPPORTED_ASSET_EXTENSIONS = {
    ".3do",
    ".cmp",
    ".cos",
    ".key",
    ".mat",
}


@dataclass(frozen = True)
class LabEntry:
    name: str
    offset: int
    size: int

    @property
    def extension(self):
        return Path(self.name).suffix.lower()


class LabArchive:
    def __init__(self, path):
        self.path = Path(path)
        self.version = None
        self.entries = []
        self.entriesByLowerName = {}
        self.Load()

    def Load(self):
        fileSize = self.path.stat().st_size

        if fileSize < 16:
            raise ValueError(f"LAB file is too small: {self.path}")

        with self.path.open("rb") as inputFile:
            header = inputFile.read(16)

            if header[0:4] != b"LABN":
                raise ValueError(f"Not a Grim LAB file: {self.path}")

            self.version = struct.unpack_from(">I", header, 4)[0]
            entryCount = struct.unpack_from("<I", header, 8)[0]
            stringTableSize = struct.unpack_from("<I", header, 12)[0]
            tableOffset = 16
            tableSize = entryCount * 16
            stringTableOffset = 16 * (entryCount + 1)

            if stringTableOffset > fileSize:
                raise ValueError(f"LAB entry table runs past end of file: {self.path}")

            inputFile.seek(tableOffset)
            tableData = inputFile.read(tableSize)

            if len(tableData) != tableSize:
                raise ValueError(f"Could not read LAB entry table: {self.path}")

            if stringTableSize <= 0 or stringTableOffset + stringTableSize > fileSize:
                firstDataOffset = FindFirstDataOffset(tableData, entryCount, fileSize)
                stringTableSize = max(0, firstDataOffset - stringTableOffset)

            inputFile.seek(stringTableOffset)
            stringTable = inputFile.read(stringTableSize)

        entries = []

        for index in range(entryCount):
            entryOffset = 16 * index
            nameOffset, dataOffset, dataSize, _unknown = struct.unpack_from(
                "<IIII",
                tableData,
                entryOffset,
            )
            name = ReadNullTerminatedString(stringTable, nameOffset)

            if dataOffset + dataSize > fileSize:
                raise ValueError(f"LAB entry runs past end of file: {name}")

            entries.append(LabEntry(
                name = name,
                offset = dataOffset,
                size = dataSize,
            ))

        entries.sort(key = lambda entry: entry.name.lower())

        self.entries = entries
        self.entriesByLowerName = {
            entry.name.lower(): entry
            for entry in entries
        }

    def Find(self, name):
        return self.entriesByLowerName.get(name.lower())

    def Filter(self, extensions = None):
        normalizedExtensions = NormalizeExtensions(extensions)

        return [
            entry
            for entry in self.entries
            if normalizedExtensions is None or entry.extension in normalizedExtensions
        ]

    def ReadEntry(self, entryOrName):
        entry = self.ResolveEntry(entryOrName)

        with self.path.open("rb") as inputFile:
            inputFile.seek(entry.offset)
            return inputFile.read(entry.size)

    def ReadEntryPrefix(self, entryOrName, size):
        entry = self.ResolveEntry(entryOrName)

        with self.path.open("rb") as inputFile:
            inputFile.seek(entry.offset)
            return inputFile.read(min(size, entry.size))

    def ExtractEntry(self, entryOrName, outputPath):
        entry = self.ResolveEntry(entryOrName)
        outputPath = Path(outputPath)
        outputPath.parent.mkdir(parents = True, exist_ok = True)

        with self.path.open("rb") as inputFile:
            inputFile.seek(entry.offset)

            with outputPath.open("wb") as outputFile:
                CopyBytes(inputFile, outputFile, entry.size)

    def Extract(self, outputFolder, extensions = None, perExtensionFolders = True):
        outputFolder = Path(outputFolder)
        extractedPaths = []

        for entry in self.Filter(extensions):
            if perExtensionFolders:
                folderName = GetFolderNameForExtension(entry.extension)
                outputPath = outputFolder / folderName / entry.name
            else:
                outputPath = outputFolder / entry.name

            self.ExtractEntry(entry, outputPath)
            extractedPaths.append(outputPath)

        return extractedPaths

    def ResolveEntry(self, entryOrName):
        if isinstance(entryOrName, LabEntry):
            return entryOrName

        entry = self.Find(str(entryOrName))

        if entry is None:
            raise KeyError(f"LAB entry not found: {entryOrName}")

        return entry


def OpenLab(path):
    return LabArchive(path)


def ReadNullTerminatedString(data, offset):
    if offset < 0 or offset >= len(data):
        raise ValueError(f"String offset outside LAB data: {offset}")

    endOffset = data.find(b"\0", offset)

    if endOffset < 0:
        endOffset = len(data)

    return data[offset:endOffset].decode("latin-1")


def FindFirstDataOffset(tableData, entryCount, fileSize):
    firstDataOffset = fileSize

    for index in range(entryCount):
        entryOffset = 16 * index
        _nameOffset, dataOffset, _dataSize, _unknown = struct.unpack_from(
            "<IIII",
            tableData,
            entryOffset,
        )

        if dataOffset < firstDataOffset:
            firstDataOffset = dataOffset

    return firstDataOffset


def NormalizeExtensions(extensions):
    if extensions is None:
        return None

    if isinstance(extensions, str):
        extensions = [extensions]

    normalizedExtensions = set()

    for extension in extensions:
        extension = extension.strip().lower()

        if extension == "" or extension == "*":
            return None

        if not extension.startswith("."):
            extension = "." + extension

        normalizedExtensions.add(extension)

    return normalizedExtensions


def GetFolderNameForExtension(extension):
    if len(extension) <= 1:
        return "no_extension"

    return extension[1:]


def CopyBytes(inputFile, outputFile, byteCount):
    remaining = byteCount
    bufferSize = 1024 * 1024

    while remaining > 0:
        chunk = inputFile.read(min(bufferSize, remaining))

        if len(chunk) == 0:
            raise EOFError("Unexpected end of LAB while extracting entry")

        outputFile.write(chunk)
        remaining -= len(chunk)


def ExtractLabAssets(labPath, outputFolder, extensions = SUPPORTED_ASSET_EXTENSIONS):
    archive = LabArchive(labPath)
    return archive.Extract(outputFolder, extensions)
