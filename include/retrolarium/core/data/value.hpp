#pragma once

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace retrolarium::core {

// Raised when a Value is read as a type it does not hold.
class ValueError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

// A JSON-shaped value, used for the parts of a profile whose shape belongs to
// a codec rather than to the profile schema.
//
// This is a tagged struct rather than a std::variant because the two container
// kinds refer back to Value: std::vector of an incomplete type is allowed,
// std::map of one is not, and hiding that behind indirection buys nothing at
// this size.
class Value final {
public:
    enum class Kind { Null, Boolean, Integer, Double, String, Array, Object };

    Value() = default;
    static Value boolean(bool value);
    static Value integer(std::int64_t value);
    static Value real(double value);
    static Value string(std::string value);
    static Value array(std::vector<Value> value);
    // std::map, so the members come back in the order sorted output needs.
    static Value object(std::map<std::string, Value> value);

    [[nodiscard]] Kind kind() const noexcept { return kind_; }
    [[nodiscard]] bool isNull() const noexcept { return kind_ == Kind::Null; }
    [[nodiscard]] bool isObject() const noexcept { return kind_ == Kind::Object; }
    [[nodiscard]] bool isArray() const noexcept { return kind_ == Kind::Array; }
    [[nodiscard]] bool isString() const noexcept { return kind_ == Kind::String; }
    [[nodiscard]] bool isInteger() const noexcept { return kind_ == Kind::Integer; }
    [[nodiscard]] bool isBoolean() const noexcept { return kind_ == Kind::Boolean; }
    [[nodiscard]] bool isDouble() const noexcept { return kind_ == Kind::Double; }

    [[nodiscard]] bool asBoolean() const;
    [[nodiscard]] std::int64_t asInteger() const;
    [[nodiscard]] double asDouble() const;
    [[nodiscard]] const std::string &asString() const;
    [[nodiscard]] const std::vector<Value> &asArray() const;
    [[nodiscard]] const std::map<std::string, Value> &asObject() const;

    // Returns nullptr rather than throwing when the member is absent, because
    // most profile fields are optional and the caller reports the field name.
    [[nodiscard]] const Value *find(const std::string &name) const;

    [[nodiscard]] bool operator==(const Value &other) const;
    [[nodiscard]] bool operator!=(const Value &other) const
    {
        return !(*this == other);
    }

private:
    Kind kind_ = Kind::Null;
    bool boolean_ = false;
    std::int64_t integer_ = 0;
    double real_ = 0.0;
    std::string string_;
    std::vector<Value> array_;
    std::map<std::string, Value> object_;
};

// JSON is how these values reach the core and how they are compared against
// the Kit, but the parser stays out of this header: it is large, and only a
// handful of translation units should pay for it.
[[nodiscard]] Value parseValue(const std::string &json);

// Rendered the way `json.dumps(value, indent=2, sort_keys=True)` renders it,
// which is what makes a document comparable to the Kit's byte for byte.
[[nodiscard]] std::string renderValue(const Value &value);

} // namespace retrolarium::core
