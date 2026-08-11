import xml.etree.ElementTree as ET
import sys
from bs4 import BeautifulSoup

enex_path = "/home/jtrom/Projects/Keep/Evernote Notebook.enex"

print("Starting sample parse of Evernote Notebook.enex...")

count = 0
try:
    # Use iterparse to parse elements sequentially
    context = ET.iterparse(enex_path, events=("start", "end"))
    context = iter(context)
    event, root = next(context)
    
    for event, elem in context:
        if event == "end" and elem.tag == "note":
            count += 1
            title = elem.findtext("title")
            created = elem.findtext("created")
            updated = elem.findtext("updated")
            tags = [tag.text for tag in elem.findall("tag") if tag.text]
            
            print(f"\n--- Note #{count} ---")
            print(f"Title:   {title}")
            print(f"Created: {created}")
            print(f"Updated: {updated}")
            print(f"Tags:    {tags}")
            
            content_xml = elem.findtext("content")
            if content_xml:
                # Clean or truncate the content to print a snippet
                soup = BeautifulSoup(content_xml, "lxml")
                text_snippet = soup.get_text()[:300].replace("\n", " ").strip()
                print(f"Content Snippet: {text_snippet}...")
            
            # Check for resources
            resources = elem.findall("resource")
            print(f"Resources count: {len(resources)}")
            for idx, r in enumerate(resources):
                mime = r.findtext("mime")
                attr = r.find("resource-attributes")
                file_name = attr.findtext("file-name") if attr is not None else None
                print(f"  - Resource #{idx+1}: {file_name} ({mime})")
            
            # Clear elements to save memory
            elem.clear()
            root.clear()
            
            if count >= 3:
                break
                
except Exception as e:
    print("An error occurred during parsing:", e)
    sys.exit(1)

print("\nSample parse completed successfully!")
