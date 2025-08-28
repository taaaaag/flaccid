# First, let's create a comprehensive metadata schema and priority matrix
import json
import pandas as pd

# Define the comprehensive metadata schema for FLAC files
metadata_schema = {
    "core_fields": {
        "TITLE": "Track title",
        "TRACKNUMBER": "Track number in album",
        "DISCNUMBER": "Disc number in multi-disc set",
        "ALBUM": "Album title",
        "ARTIST": "Primary artist(s)",
        "ALBUMARTIST": "Album artist (for compilations)",
        "COMPOSER": "Composer(s)",
        "LABEL": "Record label",
        "DATE": "Release date (YYYY-MM-DD)",
        "YEAR": "Release year",
        "GENRE": "Musical genre",
        "LANGUAGE": "Language of lyrics",
        "ISRC": "International Standard Recording Code",
        "UPC": "Universal Product Code (album barcode)",
        "DURATION": "Track duration in seconds",
        "BPM": "Beats per minute",
        "KEY": "Musical key",
        "COPYRIGHT": "Copyright information",
        "PUBLISHER": "Publishing company",
        "CATALOGNUMBER": "Catalog number",
        "COUNTRY": "Country of release",
        "LOCATION": "Recording location/studio",
        "RELEASETYPE": "EP, LP, Single, Compilation, etc.",
        "VERSION": "Version info (remaster, deluxe, etc.)",
        "COMMENT": "General comments",
        "LYRICS": "Song lyrics"
    },
    "technical_fields": {
        "BITDEPTH": "Bit depth (16, 24, etc.)",
        "SAMPLERATE": "Sample rate (44100, 96000, etc.)",
        "CHANNELS": "Number of channels",
        "REPLAYGAIN_TRACK_GAIN": "Track-level replay gain",
        "REPLAYGAIN_TRACK_PEAK": "Track-level peak",
        "REPLAYGAIN_ALBUM_GAIN": "Album-level replay gain",
        "REPLAYGAIN_ALBUM_PEAK": "Album-level peak"
    },
    "source_ids": {
        "QOBUZ_TRACK_ID": "Qobuz track identifier",
        "TIDAL_TRACK_ID": "Tidal track identifier",
        "MUSICBRAINZ_TRACKID": "MusicBrainz track identifier",
        "MUSICBRAINZ_ALBUMID": "MusicBrainz album identifier",
        "MUSICBRAINZ_ARTISTID": "MusicBrainz artist identifier",
        "ITUNES_TRACK_ID": "iTunes/Apple Music track identifier",
        "DISCOGS_RELEASE_ID": "Discogs release identifier",
        "ACOUSTID_ID": "AcousticID fingerprint identifier",
        "SPOTIFY_TRACK_ID": "Spotify track identifier"
    },
    "artwork_fields": {
        "METADATA_BLOCK_PICTURE": "FLAC native artwork block",
        "COVERART": "Base64 encoded cover art",
        "COVERARTMIME": "MIME type of cover art"
    }
}

# Define hierarchical priority matrix for metadata sources
priority_matrix = {
    "TITLE": ["qobuz", "apple", "musicbrainz", "tidal", "discogs", "acoustid"],
    "ARTIST": ["tidal", "apple", "musicbrainz", "qobuz", "discogs", "acoustid"],
    "ALBUM": ["qobuz", "musicbrainz", "apple", "tidal", "discogs", "acoustid"],
    "ALBUMARTIST": ["musicbrainz", "apple", "qobuz", "tidal", "discogs", "acoustid"],
    "GENRE": ["musicbrainz", "discogs", "qobuz", "apple", "tidal", "acoustid"],
    "DATE": ["musicbrainz", "qobuz", "apple", "discogs", "tidal", "acoustid"],
    "LABEL": ["discogs", "qobuz", "musicbrainz", "apple", "tidal", "acoustid"],
    "ISRC": ["musicbrainz", "qobuz", "tidal", "apple", "discogs", "acoustid"],
    "COMPOSER": ["musicbrainz", "apple", "qobuz", "discogs", "tidal", "acoustid"],
    "TRACKNUMBER": ["qobuz", "apple", "musicbrainz", "tidal", "discogs", "acoustid"],
    "ARTWORK": ["apple", "qobuz", "discogs", "tidal", "musicbrainz", "acoustid"],
    "LYRICS": ["apple", "qobuz", "musicbrainz", "tidal", "discogs", "acoustid"],
    "COPYRIGHT": ["discogs", "musicbrainz", "apple", "qobuz", "tidal", "acoustid"],
    "CATALOGNUMBER": ["discogs", "musicbrainz", "qobuz", "apple", "tidal", "acoustid"]
}

# Create a DataFrame for better visualization
priority_df = pd.DataFrame.from_dict(priority_matrix, orient='index')
priority_df.columns = ['1st Priority', '2nd Priority', '3rd Priority', '4th Priority', '5th Priority', '6th Priority']

print("FLAC Metadata Tagger - Hierarchical Priority Matrix")
print("=" * 60)
print(priority_df.to_string())

print("\n\nMetadata Schema Summary:")
print(f"Core Fields: {len(metadata_schema['core_fields'])} fields")
print(f"Technical Fields: {len(metadata_schema['technical_fields'])} fields") 
print(f"Source IDs: {len(metadata_schema['source_ids'])} fields")
print(f"Artwork Fields: {len(metadata_schema['artwork_fields'])} fields")
print(f"Total Fields: {sum(len(v) for v in metadata_schema.values())} fields")

# Save the schema to a JSON file
with open('flac_metadata_schema.json', 'w') as f:
    json.dump(metadata_schema, f, indent=2)

# Save priority matrix to CSV
priority_df.to_csv('metadata_priority_matrix.csv')

print("\nFiles created:")
print("- flac_metadata_schema.json")
print("- metadata_priorcd ..ity_matrix.csv")