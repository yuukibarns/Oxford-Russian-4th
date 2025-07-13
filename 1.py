import re
import json
from bs4 import BeautifulSoup
from tqdm import tqdm  # Add this import

# Map vowels to their accented versions
ACCENT_MAP = {
    "а": "а́",
    "е": "е́",
    "и": "и́",
    "о": "о́",
    "у": "у́",
    "ы": "ы́",
    "э": "э́",
    "ю": "ю́",
    "я": "я́",
    "А": "А́",
    "Е": "Е́",
    "И": "И́",
    "О": "О́",
    "У": "У́",
    "Ы": "Ы́",
    "Э": "Э́",
    "Ю": "Ю́",
    "Я": "Я́",
}


def extract_reading(html_str, headword):
    """Extract reading from html string using headword structure as guide"""
    soup = BeautifulSoup(html_str, "html.parser")

    # Get the first div in the document
    first_div = soup.find("div")
    if not first_div or "◉" not in first_div.get_text():
        return None

    # Now look for dimgray span within this div
    dimgray_span = first_div.find("span", style=lambda s: s and "color:dimgray" in s)
    if not dimgray_span:
        return None

    # Extract text content while preserving <u> tags for accent processing
    reading_str = ""
    for child in dimgray_span.children:
        if child.name == "u":
            vowel = child.get_text()
            reading_str += ACCENT_MAP.get(vowel, vowel)
        elif child.name is None:  # Text node
            reading_str += child.string

    # Remove all pipe characters
    reading_str = reading_str.replace("|", "")

    # Calculate headword space count
    headword_space_count = headword.count(" ")

    # Split reading string into segments
    segments = []
    current_segment = []
    current_space_count = 0

    for char in reading_str:
        if char in ",;":
            if current_segment:  # Only add if not empty
                segments.append("".join(current_segment).strip())
                current_segment = []
                current_space_count = 0
        elif char == " ":
            current_space_count += 1
            if current_space_count > headword_space_count:
                if current_segment:  # Only add if not empty
                    segments.append("".join(current_segment).strip())
                break
            current_segment.append(char)
        else:
            current_segment.append(char)

    # Add the last segment if exists
    if current_segment:
        segments.append("".join(current_segment).strip())

    # Take the first valid segment
    base_reading = segments[0] if segments else reading_str

    base_reading = base_reading.strip().rstrip(":")

    # Handle optional parts in parentheses (like бранч(л)ивый)
    if "(" in base_reading and ")" in base_reading:
        # Find the variant that matches headword best
        variants = [
            re.sub(r"\([^)]*\)", "", base_reading),  # Without optional parts
            re.sub(r"\(([^)]+)\)", r"\1", base_reading),  # With optional
        ]

        # Normalize both strings for comparison
        def normalize(s):
            return (
                s.replace("ё", "е")
                .replace("\u0301", "")
                .replace("-", "")
                .replace(" ", "")
                .lower()
            )

        norm_headword = normalize(headword)

        for variant in variants:
            if normalize(variant) == norm_headword:
                base_reading = variant
                break

    # Strip again
    # Special: о...(also
    base_reading = re.split(r"[,(]", base_reading, maxsplit=1)[0].strip()

    # Count vowels in base reading (ignoring accents)
    vowel_count = sum(
        1 for char in base_reading.replace("\u0301", "") if char.lower() in "аеиоуыэюя"
    )

    # Remove accents for single-vowel words
    if vowel_count == 1:
        base_reading = base_reading.replace("\u0301", "")

    return base_reading.strip()


def convert_style(style_str):
    """Convert HTML style to Yomitan style object"""
    if not style_str:
        return {}

    styles = {}
    for prop in style_str.split(";"):
        prop = prop.strip()
        if ":" not in prop:
            continue
        key, value = [p.strip() for p in prop.split(":", 1)]

        if key == "color":
            styles["color"] = value
        elif key == "margin-left":
            styles["marginLeft"] = value
        elif key == "font-style" and value == "italic":
            styles["fontStyle"] = "italic"
        elif key == "font-weight" and value == "bold":
            styles["fontWeight"] = "bold"
        elif key == "text-decoration" and value == "underline":
            styles["textDecorationLine"] = "underline"

    return styles


def convert_html_to_content(html_str):
    """Convert HTML fragment to Yomitan structured content"""
    # Wrap in a div for proper parsing
    soup = BeautifulSoup(f"<div>{html_str}</div>", "html.parser")
    root = soup.div

    def process_node(node):
        """Recursively process HTML nodes"""
        if node.name is None:  # Text node
            return str(node)

        # Handle different element types
        if node.name in ["div", "span"]:
            tag = node.name
        elif node.name == "a" and node.get("href"):
            tag = "a"
        else:
            tag = "span"

        # Process children
        content = []
        for child in node.children:
            processed = process_node(child)
            if processed:
                content.append(processed)

        # Handle empty content
        if not content:
            content = [""]

        # Create node object
        node_obj = {"tag": tag, "content": content}

        # Special handling for <a> tags
        if node.name == "a" and node.get("href"):
            # Convert internal links to Yomitan format (prepend with ?)
            href = node["href"]
            if not href.startswith(("http:", "https:", "?")):
                href = f"?query={href}&wildcards=off"
            node_obj["href"] = href

        # Add styling if available
        style = convert_style(node.get("style", ""))
        if style:
            node_obj["style"] = style

        # Special handling for <i> and <b> tags
        if node.name == "i" and "fontStyle" not in node_obj.get("style", {}):
            node_obj.setdefault("style", {})["fontStyle"] = "italic"
        if node.name == "b" and "fontWeight" not in node_obj.get("style", {}):
            node_obj.setdefault("style", {})["fontWeight"] = "bold"
        if node.name == "u" and "textDecorationLine" not in node_obj.get("style", {}):
            node_obj.setdefault("style", {})["textDecorationLine"] = "underline"

        # Handle class attribute
        if node.get("class"):
            node_obj.setdefault("data", {})["class"] = " ".join(node["class"])

        return node_obj

    return process_node(root)


def convert_to_yomitan(input_lines, debug=False):
    """Convert Oxford Russian dictionary to Yomitan JSON format"""
    entries = []

    non_empty_lines = [line for line in input_lines if line.strip()]

    for idx, line in enumerate(
        tqdm(non_empty_lines, desc="Processing entries", unit="entry")
    ):
        if not line.strip():
            continue

        line_copy = line

        line = line.replace("\\n", "").strip()
        parts = line.split("<", 1)
        if len(parts) < 2:
            continue

        headword = parts[0].strip()
        def_html = "<" + parts[1].strip()

        reading = extract_reading(def_html, headword) or headword

        # Normalize both strings for comparison
        def normalize(s):
            return (
                s.replace("ё", "е")
                .replace("\u0301", "")
                .replace("-", "")
                .replace(" ", "")
                .lower()
            )

        norm_reading = normalize(reading)
        norm_headword = normalize(headword)

        try:
            if norm_reading != norm_headword:
                raise ValueError(
                    f"Reading validation failed: '{reading}'"
                    f"doesn't match headword '{headword}'\n"
                    f"norm_reading '{norm_reading}'\n"
                    f"norm_headword '{norm_headword}'"
                )

            # Convert HTML to structured content
            structured_content = convert_html_to_content(def_html)

            # Build Yomitan entry with proper schema compliance
            entry = [
                headword,  # Term
                reading,  # Reading
                "",  # Definition tags
                "",  # Rules
                0,  # Score
                [{"type": "structured-content", "content": structured_content}],
                idx,  # Sequence
                "",  # Term tags
            ]
            entries.append(entry)

        except ValueError as e:
            # Write the line_copy to test.txt when ValueError is raised
            if debug:
                with open("test.txt", "a", encoding="utf-8") as f:
                    f.write(line_copy)
            # Re-raise the exception if you want to stop execution or handle it elsewhere
            raise e

    return entries


# Example usage
if __name__ == "__main__":
    # First try the test file
    with open("test.txt", "r", encoding="utf-8") as f:
        test_lines = f.readlines()

    test_data = convert_to_yomitan(test_lines)

    # Read input from file
    with open("Ru-En_Oxf_Russian4th_v1_1.txt", "r", encoding="utf-8") as f:
        input_lines = f.readlines()

    # Convert to Yomitan format
    yomitan_data = convert_to_yomitan(input_lines, debug=True)

    # Write output to JSON file
    with open("term_bank_1.json", "w", encoding="utf-8") as f:
        json.dump(yomitan_data, f, ensure_ascii=False, indent=2)
