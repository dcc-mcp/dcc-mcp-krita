from dcc_mcp_core.skill import run_main

from dcc_mcp_krita.skill_tools import bridge_main

main = bridge_main("krita.get_status", "Krita bridge is ready.")

if __name__ == "__main__":
    run_main(main)
