from docling.document_converter import DocumentConverter
import inspect

try:
    print("Checking DocumentConverter methods:")
    print(f"Has convert_string: {hasattr(DocumentConverter, 'convert_string')}")
    print(f"Has convert_from_string: {hasattr(DocumentConverter, 'convert_from_string')}")
    
    if hasattr(DocumentConverter, 'convert_string'):
        print("\nSignature of convert_string:")
        print(inspect.signature(DocumentConverter.convert_string))

    # Check for InputFormat
    try:
        from docling.datamodel.base_models import InputFormat
        print(f"\nFound InputFormat in docling.datamodel.base_models: {InputFormat.HTML}")
    except ImportError:
        print("\nInputFormat not found in docling.datamodel.base_models")
        try:
            from docling.document_converter import InputFormat
            print(f"Found InputFormat in docling.document_converter: {InputFormat.HTML}")
        except ImportError:
             print("Could not find InputFormat")

except Exception as e:
    print(f"Error: {e}")
