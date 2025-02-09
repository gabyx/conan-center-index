from conan.tools.files import rename
from conans import ConanFile, tools, AutoToolsBuildEnvironment
from contextlib import contextmanager
import os

required_conan_version = ">=1.43.0"


class LibiconvConan(ConanFile):
    name = "libiconv"
    description = "Convert text to and from Unicode"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://www.gnu.org/software/libiconv/"
    topics = ("libiconv", "iconv", "text", "encoding", "locale", "unicode", "conversion")
    license = "LGPL-2.1"

    settings = "os", "arch", "compiler", "build_type"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
    }

    _autotools = None

    @property
    def _source_subfolder(self):
        return "source_subfolder"

    @property
    def _use_winbash(self):
        return tools.os_info.is_windows and (self.settings.compiler == "gcc" or tools.cross_building(self))

    @property
    def _is_msvc(self):
        return str(self.settings.compiler) in ["Visual Studio", "msvc"]

    @property
    def _is_clang_cl(self):
        return self.settings.compiler == "clang" and self.settings.os == "Windows"

    def export_sources(self):
        for patch in self.conan_data.get("patches", {}).get(self.version, []):
            self.copy(patch["patch_file"])

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def configure(self):
        if self.options.shared:
            del self.options.fPIC
        del self.settings.compiler.libcxx
        del self.settings.compiler.cppstd

    @property
    def _settings_build(self):
        return getattr(self, "settings_build", self.settings)

    def build_requirements(self):
        if self._settings_build.os == "Windows" and not tools.get_env("CONAN_BASH_PATH"):
            self.build_requires("msys2/cci.latest")

    def source(self):
        tools.get(**self.conan_data["sources"][self.version], destination=self._source_subfolder, strip_root=True)

    @contextmanager
    def _build_context(self):
        env_vars = {}
        if self._is_msvc or self._is_clang_cl:
            cc = "cl" if self._is_msvc else os.environ.get("CC", "clang-cl")
            cxx = "cl" if self._is_msvc else os.environ.get("CXX", "clang-cl")
            lib = "lib" if self._is_msvc else os.environ.get("AR", "llvm-lib")
            build_aux_path = os.path.join(self.build_folder, self._source_subfolder, "build-aux")
            lt_compile = tools.unix_path(os.path.join(build_aux_path, "compile"))
            lt_ar = tools.unix_path(os.path.join(build_aux_path, "ar-lib"))
            env_vars.update({
                "CC": "{} {} -nologo".format(lt_compile, cc),
                "CXX": "{} {} -nologo".format(lt_compile, cxx),
                "LD": "link",
                "STRIP": ":",
                "AR": "{} {}".format(lt_ar, lib),
                "RANLIB": ":",
                "NM": "dumpbin -symbols"
            })
            env_vars["win32_target"] = "_WIN32_WINNT_VISTA"

        if not tools.cross_building(self) or self._is_msvc or self._is_clang_cl:
            rc = None
            if self.settings.arch == "x86":
                rc = "windres --target=pe-i386"
            elif self.settings.arch == "x86_64":
                rc = "windres --target=pe-x86-64"
            if rc:
                env_vars["RC"] = rc
                env_vars["WINDRES"] = rc
        if self._use_winbash:
            env_vars["RANLIB"] = ":"

        with tools.vcvars(self.settings) if (self._is_msvc or self._is_clang_cl) else tools.no_op():
            with tools.chdir(self._source_subfolder):
                with tools.environment_append(env_vars):
                    yield

    def _configure_autotools(self):
        if self._autotools:
            return self._autotools
        host = None
        build = None
        if self._is_msvc or self._is_clang_cl:
            build = False
            if self.settings.arch == "x86":
                host = "i686-w64-mingw32"
            elif self.settings.arch == "x86_64":
                host = "x86_64-w64-mingw32"

        self._autotools = AutoToolsBuildEnvironment(self, win_bash=tools.os_info.is_windows)

        configure_args = []
        if self.options.shared:
            configure_args.extend(["--disable-static", "--enable-shared"])
        else:
            configure_args.extend(["--enable-static", "--disable-shared"])

        if (self.settings.compiler == "Visual Studio" and tools.Version(self.settings.compiler.version) >= "12") or \
           self.settings.compiler == "msvc":
            self._autotools.flags.append("-FS")

        self._autotools.configure(args=configure_args, host=host, build=build)
        return self._autotools

    def _patch_sources(self):
        for patch in self.conan_data.get("patches", {}).get(self.version, []):
            tools.patch(**patch)
        # relocatable shared libs on macOS
        for configure in ["configure", os.path.join("libcharset", "configure")]:
            tools.replace_in_file(os.path.join(self._source_subfolder, configure),
                                  "-install_name \\$rpath/", "-install_name @rpath/")

    def build(self):
        self._patch_sources()
        with self._build_context():
            autotools = self._configure_autotools()
            autotools.make()

    def package(self):
        self.copy("COPYING.LIB", src=self._source_subfolder, dst="licenses")
        with self._build_context():
            autotools = self._configure_autotools()
            autotools.install()

        tools.remove_files_by_mask(os.path.join(self.package_folder, "lib"), "*.la")
        tools.rmdir(os.path.join(self.package_folder, "share"))

        if (self._is_msvc or self._is_clang_cl) and self.options.shared:
            for import_lib in ["iconv", "charset"]:
                rename(self, os.path.join(self.package_folder, "lib", "{}.dll.lib".format(import_lib)),
                             os.path.join(self.package_folder, "lib", "{}.lib".format(import_lib)))

    def package_info(self):
        self.cpp_info.set_property("cmake_find_mode", "both")
        self.cpp_info.set_property("cmake_file_name", "Iconv")
        self.cpp_info.set_property("cmake_target_name", "Iconv::Iconv")

        self.cpp_info.names["cmake_find_package"] = "Iconv"
        self.cpp_info.names["cmake_find_package_multi"] = "Iconv"

        self.cpp_info.libs = ["iconv", "charset"]

        binpath = os.path.join(self.package_folder, "bin")
        self.output.info("Appending PATH environment var: {}".format(binpath))
        self.env_info.path.append(binpath)
