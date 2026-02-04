#!/bin/bash
#
# cleanup-unavailable.sh
# Removes unavailable media files from Plex server
#
# This script crawls through your Plex libraries and removes media entries
# where the underlying file is no longer accessible (marked as unavailable).
#

set -euo pipefail

# Configuration - Set these environment variables or modify defaults
PLEX_URL="${PLEX_URL:-http://localhost:32400}"
PLEX_TOKEN="${PLEX_TOKEN:-}"

# Flags
DRY_RUN="${DRY_RUN:-true}"  # Set to "false" to actually delete
VERBOSE="${VERBOSE:-false}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" >&2
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" >&2
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" >&2
}

log_verbose() {
    if [[ "$VERBOSE" == "true" ]]; then
        echo -e "${BLUE}[DEBUG]${NC} $1" >&2
    fi
}

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Removes unavailable media files from Plex server.

Options:
    -u, --url URL           Plex server URL (default: http://localhost:32400)
    -t, --token TOKEN       Plex authentication token (required)
    -d, --delete            Actually delete unavailable media (default: dry run)
    -v, --verbose           Enable verbose output
    -h, --help              Show this help message

Environment variables:
    PLEX_URL                Plex server URL
    PLEX_TOKEN              Plex authentication token
    DRY_RUN                 Set to "false" to delete (default: true)
    VERBOSE                 Set to "true" for debug output

Examples:
    # Dry run (see what would be deleted)
    $(basename "$0") -t YOUR_PLEX_TOKEN

    # Actually delete unavailable media
    $(basename "$0") -t YOUR_PLEX_TOKEN --delete

    # Using environment variables
    export PLEX_TOKEN="your-token"
    export PLEX_URL="http://plex.local:32400"
    $(basename "$0") --delete

How to get your Plex token:
    1. Sign in to Plex Web App
    2. Browse to any media item
    3. Click "Get Info" -> "View XML"
    4. Look for "X-Plex-Token" in the URL

EOF
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--url)
            PLEX_URL="$2"
            shift 2
            ;;
        -t|--token)
            PLEX_TOKEN="$2"
            shift 2
            ;;
        -d|--delete)
            DRY_RUN="false"
            shift
            ;;
        -v|--verbose)
            VERBOSE="true"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            ;;
    esac
done

# Validate required parameters
if [[ -z "$PLEX_TOKEN" ]]; then
    log_error "Plex token is required. Use -t/--token or set PLEX_TOKEN environment variable."
    echo ""
    usage
fi

# Remove trailing slash from URL
PLEX_URL="${PLEX_URL%/}"

# API helper function
plex_api() {
    local endpoint="$1"
    local method="${2:-GET}"

    curl -s -X "$method" \
        -H "X-Plex-Token: ${PLEX_TOKEN}" \
        -H "Accept: application/json" \
        "${PLEX_URL}${endpoint}"
}

# Check if jq is available
check_dependencies() {
    if ! command -v jq &> /dev/null; then
        log_error "jq is required but not installed. Please install jq."
        exit 1
    fi

    if ! command -v curl &> /dev/null; then
        log_error "curl is required but not installed. Please install curl."
        exit 1
    fi
}

# Test connection to Plex server
test_connection() {
    log_info "Testing connection to Plex server at ${PLEX_URL}..."

    local response
    response=$(plex_api "/" 2>&1)

    if [[ $? -ne 0 ]] || [[ -z "$response" ]]; then
        log_error "Failed to connect to Plex server at ${PLEX_URL}"
        exit 1
    fi

    local server_name
    server_name=$(echo "$response" | jq -r '.MediaContainer.friendlyName // empty' 2>/dev/null)

    if [[ -n "$server_name" ]]; then
        log_success "Connected to Plex server: ${server_name}"
    else
        log_warn "Connected but couldn't get server name. Proceeding anyway..."
    fi
}

# Get all library sections
get_libraries() {
    plex_api "/library/sections" | jq -r '.MediaContainer.Directory[] | "\(.key)|\(.title)|\(.type)"'
}

# Get all items in a library section
get_library_items() {
    local section_key="$1"
    local library_type="$2"

    # For TV shows, we need to go deeper
    if [[ "$library_type" == "show" ]]; then
        plex_api "/library/sections/${section_key}/all?type=4" | jq -r '.MediaContainer.Metadata[]? | "\(.ratingKey)|\(.grandparentTitle // "Unknown") - \(.parentTitle // "Unknown") - \(.title // "Unknown")"'
    else
        plex_api "/library/sections/${section_key}/all" | jq -r '.MediaContainer.Metadata[]? | "\(.ratingKey)|\(.title // "Unknown")"'
    fi
}

# Check if a file is accessible via HEAD request
# Returns 0 if unavailable (404), 1 if available
check_file_accessible() {
    local part_key="$1"

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" -I \
        -H "X-Plex-Token: ${PLEX_TOKEN}" \
        "${PLEX_URL}${part_key}")

    if [[ "$http_code" == "404" ]]; then
        return 0  # Unavailable
    else
        return 1  # Available
    fi
}

# Check if a media item has unavailable parts
check_media_parts() {
    local rating_key="$1"

    local metadata
    metadata=$(plex_api "/library/metadata/${rating_key}")

    # Get all media parts with their keys for accessibility checking
    local parts_info
    parts_info=$(echo "$metadata" | jq -r '
        .MediaContainer.Metadata[0].Media[]? |
        .id as $media_id |
        .Part[]? |
        {
            media_id: $media_id,
            part_id: .id,
            part_key: .key,
            file: .file
        }
    ' 2>/dev/null)

    if [[ -z "$parts_info" ]]; then
        return
    fi

    # Parse each part and check accessibility via HEAD request
    while IFS= read -r part; do
        if [[ -z "$part" ]]; then
            continue
        fi

        local media_id part_id part_key file
        media_id=$(echo "$part" | jq -r '.media_id')
        part_id=$(echo "$part" | jq -r '.part_id')
        part_key=$(echo "$part" | jq -r '.part_key')
        file=$(echo "$part" | jq -r '.file')

        log_verbose "  Checking part: ${file}"
        log_verbose "    Part key: ${part_key}"

        # Check if the file is accessible by making a HEAD request
        if check_file_accessible "$part_key"; then
            log_verbose "    Status: UNAVAILABLE (404)"
            echo "${media_id}|${part_id}|${file}"
        else
            log_verbose "    Status: Available"
        fi
    done <<< "$(echo "$parts_info" | jq -c '.')"
}

# Delete a specific media version
delete_media() {
    local rating_key="$1"
    local media_id="$2"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_warn "[DRY RUN] Would delete media ID ${media_id} from item ${rating_key}"
        return 0
    fi

    log_info "Deleting media ID ${media_id} from item ${rating_key}..."

    local response
    response=$(plex_api "/library/metadata/${rating_key}/media/${media_id}" "DELETE")

    if [[ $? -eq 0 ]]; then
        log_success "Deleted media ID ${media_id}"
        return 0
    else
        log_error "Failed to delete media ID ${media_id}"
        return 1
    fi
}

# Main cleanup function
cleanup_library() {
    local section_key="$1"
    local section_title="$2"
    local section_type="$3"

    log_info "Processing library: ${section_title} (${section_type})"

    local items_found=0
    local unavailable_found=0
    local deleted_count=0

    while IFS='|' read -r rating_key title; do
        if [[ -z "$rating_key" ]]; then
            continue
        fi

        items_found=$((items_found + 1))

        # Show progress every 50 items
        if (( items_found % 50 == 0 )); then
            log_info "  Progress: ${items_found} items checked..."
        fi

        log_verbose "Checking: ${title}"

        # Check for unavailable parts
        local unavailable
        unavailable=$(check_media_parts "$rating_key")

        if [[ -n "$unavailable" ]]; then
            while IFS='|' read -r media_id part_id file; do
                if [[ -z "$media_id" ]]; then
                    continue
                fi

                unavailable_found=$((unavailable_found + 1))
                log_warn "Found unavailable: ${title}"
                log_warn "  File: ${file}"

                if delete_media "$rating_key" "$media_id"; then
                    deleted_count=$((deleted_count + 1))
                fi
            done <<< "$unavailable"
        fi

    done < <(get_library_items "$section_key" "$section_type")

    log_info "Library '${section_title}' summary:"
    log_info "  Items checked: ${items_found}"
    log_info "  Unavailable found: ${unavailable_found}"
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "  Would delete: ${deleted_count}"
    else
        log_info "  Deleted: ${deleted_count}"
    fi
    echo ""
}

# Alternative: Trigger Plex's built-in empty trash function
empty_trash() {
    local section_key="$1"

    log_info "Emptying trash for library section ${section_key}..."
    plex_api "/library/sections/${section_key}/emptyTrash" "PUT"
}

# Main execution
main() {
    echo ""
    echo "=================================="
    echo "  Plex Unavailable Media Cleanup"
    echo "=================================="
    echo ""

    if [[ "$DRY_RUN" == "true" ]]; then
        log_warn "Running in DRY RUN mode. No changes will be made."
        log_warn "Use --delete flag to actually remove unavailable media."
        echo ""
    else
        log_warn "DESTRUCTIVE MODE: Unavailable media WILL be deleted!"
        echo ""
        read -p "Are you sure you want to proceed? (yes/no): " confirm
        if [[ "$confirm" != "yes" ]]; then
            log_info "Aborted by user."
            exit 0
        fi
        echo ""
    fi

    check_dependencies
    test_connection

    echo ""
    log_info "Fetching library sections..."

    local total_unavailable=0

    while IFS='|' read -r section_key section_title section_type; do
        if [[ -z "$section_key" ]]; then
            continue
        fi

        # Only process movie and TV show libraries
        if [[ "$section_type" == "movie" ]] || [[ "$section_type" == "show" ]]; then
            cleanup_library "$section_key" "$section_title" "$section_type"
        else
            log_info "Skipping library '${section_title}' (type: ${section_type})"
        fi
    done < <(get_libraries)

    echo ""
    echo "=================================="
    echo "  Cleanup Complete"
    echo "=================================="

    if [[ "$DRY_RUN" == "true" ]]; then
        echo ""
        log_info "This was a dry run. To actually delete, run with --delete flag."
    fi
}

main "$@"
